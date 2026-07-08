import json
import torch
import os
import sys
import numpy as np
from rdkit import Chem
from rdkit.Chem import Descriptors
from rdkit.ML.Descriptors import MoleculeDescriptors
import sklearn
import sklearn.ensemble
import sklearn.impute
import sklearn.linear_model
import sklearn.pipeline
import sklearn.preprocessing
import sklearn.svm
import sklearn.tree
import re
import time
import socket
from urllib.parse import quote
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from sklearn.neighbors import NearestNeighbors


# ============================================================
# CORS HEADERS
# ============================================================

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "OPTIONS,POST",
    "Content-Type": "application/json",
}


# ============================================================
# MODEL / API SETTINGS
# ============================================================

MODEL_ARTIFACT_NAME = "best_voting_model_panelb_with_AD.pt"

REQUIRED_ARTIFACT_KEYS = {
    "model",
    "feature_names",
    "class_labels",
    "train_col_means",
    "applicability_domain",
}

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
CACTUS = "https://cactus.nci.nih.gov/chemical/structure"

# Important:
# Keep this low because API Gateway commonly times out around 29 seconds.
# Your old code used timeout=500, which can cause 504 Gateway Timeout.
HTTP_TIMEOUT_SECONDS = 12
HTTP_RETRIES = 2
HTTP_RETRY_DELAY_SECONDS = 1

_CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")

# Warm Lambda cache. This persists only while the Lambda container stays warm.
CAS_SMILES_CACHE = {}


# ============================================================
# MODEL LOADING HELPERS
# ============================================================

def register_sklearn_pickle_compat_modules():
    """
    Some sklearn loss classes pickle with the top-level module name "_loss".
    Register the installed sklearn Cython loss module under that name before loading.
    """
    try:
        import sklearn._loss._loss as sklearn_loss
        sys.modules.setdefault("_loss", sklearn_loss)
    except Exception:
        pass


def load_model_artifact():
    """
    Loads the trained VotingClassifier artifact with applicability-domain metadata.
    """
    model_path = os.path.join(os.path.dirname(__file__), MODEL_ARTIFACT_NAME)

    try:
        register_sklearn_pickle_compat_modules()

        try:
            artifact = torch.load(
                model_path,
                map_location=torch.device("cpu"),
                weights_only=False,
            )
        except TypeError:
            artifact = torch.load(model_path, map_location=torch.device("cpu"))

        if not isinstance(artifact, dict):
            return {"error": "Loaded model artifact is not a dictionary."}

        missing_keys = sorted(REQUIRED_ARTIFACT_KEYS.difference(artifact.keys()))

        if missing_keys:
            return {
                "error": (
                    "Model artifact is missing required key(s): "
                    + ", ".join(missing_keys)
                )
            }

        return artifact

    except Exception as e:
        return {"error": f"Error loading model artifact: {str(e)}"}


# ============================================================
# HTTP / CAS LOOKUP HELPERS
# ============================================================

def _normalize_cas(cas: str) -> str:
    """
    Normalize CAS input and replace non-ASCII hyphens with standard hyphen.
    """
    s = (cas or "").strip()

    return (
        s.replace("\u2010", "-")
         .replace("\u2011", "-")
         .replace("\u2012", "-")
         .replace("\u2013", "-")
         .replace("\u2212", "-")
    )


def _http_get(url: str, timeout: int = HTTP_TIMEOUT_SECONDS) -> bytes:
    """
    HTTP GET with a short timeout to avoid API Gateway 504 errors.
    """
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urlopen(req, timeout=timeout) as r:
        return r.read()


def _http_get_json(url: str, timeout: int = HTTP_TIMEOUT_SECONDS) -> dict:
    raw = _http_get(url, timeout=timeout)
    return json.loads(raw.decode("utf-8"))


def _http_get_text(url: str, timeout: int = HTTP_TIMEOUT_SECONDS) -> str:
    raw = _http_get(url, timeout=timeout)
    return raw.decode("utf-8").strip()


def _retry(fn, tries: int = HTTP_RETRIES, delay: float = HTTP_RETRY_DELAY_SECONDS):
    """
    Retry short network calls.

    This catches HTTP errors, URL errors, and timeout errors.
    The timeout is intentionally short to prevent API Gateway 504 responses.
    """
    last = None

    for attempt in range(tries):
        try:
            return fn()
        except (HTTPError, URLError, TimeoutError, socket.timeout) as e:
            last = e
            print(
                f"HTTP attempt {attempt + 1}/{tries} failed: {repr(e)}",
                flush=True,
            )

            if attempt < tries - 1:
                time.sleep(delay)

    if last:
        raise last


# ============================================================
# PUBCHEM / CACTUS RESOLUTION
# ============================================================

def _pubchem_cids_by_rn(cas_rn: str):
    """
    Resolve PubChem CID using CAS Registry Number.
    """
    url = f"{PUBCHEM}/compound/xref/RN/{quote(cas_rn)}/cids/JSON"
    data = _retry(lambda: _http_get_json(url))

    ids = data.get("IdentifierList", {}).get("CID", [])

    return ids


def _pubchem_cid_via_sid_rn(cas_rn: str):
    """
    Some records exist only as PubChem substances.
    This maps SID to CID.
    """
    url_sids = f"{PUBCHEM}/substance/xref/RN/{quote(cas_rn)}/sids/JSON"
    sid_data = _retry(lambda: _http_get_json(url_sids))

    sids = sid_data.get("IdentifierList", {}).get("SID", [])

    if not sids:
        return None

    sid = sids[0]

    url_cids = f"{PUBCHEM}/substance/sid/{sid}/cids/JSON"
    cid_data = _retry(lambda: _http_get_json(url_cids))

    info = cid_data.get("InformationList", {}).get("Information", [])

    if info and "CID" in info[0]:
        cids = info[0]["CID"]
    else:
        cids = cid_data.get("IdentifierList", {}).get("CID", [])

    return cids[0] if cids else None


def _pubchem_smiles_from_cid(cid: int) -> str | None:
    """
    Retrieve CanonicalSMILES or IsomericSMILES from PubChem CID.
    """
    url = (
        f"{PUBCHEM}/compound/cid/{cid}/property/"
        "CanonicalSMILES,IsomericSMILES/JSON"
    )

    data = _retry(lambda: _http_get_json(url))

    props = data.get("PropertyTable", {}).get("Properties", [])

    if not props:
        return None

    entry = props[0]

    return entry.get("CanonicalSMILES") or entry.get("IsomericSMILES")


def _pubchem_smiles_by_name(identifier: str) -> str | None:
    """
    Resolve SMILES using PubChem compound/name lookup.
    This mirrors the legacy PubChemPy get_compounds(cas, "name") behavior.
    """
    url = (
        f"{PUBCHEM}/compound/name/{quote(identifier)}/property/"
        "CanonicalSMILES,IsomericSMILES/JSON"
    )

    data = _retry(lambda: _http_get_json(url))
    props = data.get("PropertyTable", {}).get("Properties", [])

    if not props:
        return None

    entry = props[0]
    return entry.get("CanonicalSMILES") or entry.get("IsomericSMILES")


def _cactus_smiles(identifier: str) -> str | None:
    """
    Resolve SMILES using NIH Cactus.
    """
    safe_identifier = quote(identifier)
    url = f"{CACTUS}/{safe_identifier}/smiles"

    try:
        txt = _retry(lambda: _http_get_text(url))

        if not txt or "Not Found" in txt:
            return None

        return txt

    except (HTTPError, URLError, TimeoutError, socket.timeout):
        return None


def get_smiles_from_cas(cas_number: str) -> str | None:
    """
    Resolve SMILES from a CAS number.

    Order:
    1. Check warm Lambda cache
    2. PubChem CAS RN -> CID -> SMILES
    3. PubChem SID -> CID -> SMILES
    4. PubChem compound/name fallback
    5. NIH Cactus fallback

    Returns None if not found.
    Raises network errors only if PubChem fails and Cactus also cannot resolve.
    """
    cas = _normalize_cas(cas_number)

    if not _CAS_RE.match(cas):
        raise ValueError(f"Invalid CAS format: {cas!r}")

    if cas in CAS_SMILES_CACHE:
        print(f"SMILES cache hit for CAS: {cas}", flush=True)
        return CAS_SMILES_CACHE[cas]

    print(f"Resolving SMILES for CAS: {cas}", flush=True)

    # 1. PubChem RN lookup
    try:
        t = time.time()
        cids = _pubchem_cids_by_rn(cas)
        print(
            f"PubChem RN lookup time: {time.time() - t:.2f} seconds",
            flush=True,
        )

        cid = None

        if cids:
            cid = cids[0]
        else:
            t = time.time()
            cid = _pubchem_cid_via_sid_rn(cas)
            print(
                f"PubChem SID-to-CID lookup time: {time.time() - t:.2f} seconds",
                flush=True,
            )

        if cid:
            t = time.time()
            smi = _pubchem_smiles_from_cid(cid)
            print(
                f"PubChem CID-to-SMILES lookup time: {time.time() - t:.2f} seconds",
                flush=True,
            )

            if smi:
                CAS_SMILES_CACHE[cas] = smi
                return smi

    except (HTTPError, URLError, TimeoutError, socket.timeout) as e:
        print(
            f"PubChem lookup failed for CAS {cas}: {repr(e)}",
            flush=True,
        )

        try:
            t = time.time()
            smi = _pubchem_smiles_by_name(cas)
            print(
                f"PubChem name-to-SMILES fallback time: {time.time() - t:.2f} seconds",
                flush=True,
            )

            if smi:
                CAS_SMILES_CACHE[cas] = smi
                return smi

        except (HTTPError, URLError, TimeoutError, socket.timeout) as name_error:
            print(
                f"PubChem name lookup failed for CAS {cas}: {repr(name_error)}",
                flush=True,
            )

        # Try Cactus before giving up.
        t = time.time()
        smi = _cactus_smiles(cas)
        print(
            f"Cactus fallback lookup time: {time.time() - t:.2f} seconds",
            flush=True,
        )

        if smi:
            CAS_SMILES_CACHE[cas] = smi
            return smi

        raise

    # 2. PubChem name fallback if RN/SID was reachable but had no usable match.
    try:
        t = time.time()
        smi = _pubchem_smiles_by_name(cas)
        print(
            f"PubChem name-to-SMILES fallback time: {time.time() - t:.2f} seconds",
            flush=True,
        )

        if smi:
            CAS_SMILES_CACHE[cas] = smi
            return smi

    except (HTTPError, URLError, TimeoutError, socket.timeout) as e:
        print(
            f"PubChem name lookup failed for CAS {cas}: {repr(e)}",
            flush=True,
        )

    # 3. Cactus fallback if PubChem had no usable match.
    t = time.time()
    smi = _cactus_smiles(cas)
    print(
        f"Cactus fallback lookup time: {time.time() - t:.2f} seconds",
        flush=True,
    )

    if smi:
        CAS_SMILES_CACHE[cas] = smi

    return smi


# ============================================================
# FEATURE GENERATION
# ============================================================

def qsar_ready_smiles(smiles: str) -> str:
    """
    Converts a SMILES string into a QSAR-ready version:
    canonical and without stereochemistry.
    """
    try:
        mol = Chem.MolFromSmiles(smiles)

        if mol:
            return Chem.MolToSmiles(
                mol,
                canonical=True,
                isomericSmiles=False,
            )

        return None

    except Exception:
        return None


def generate_rdkit_features(smiles: str) -> dict:
    """
    Generate RDKit molecular descriptors for one molecule.
    Missing descriptor values are preserved as NaN for the trained imputer.
    """
    mol = Chem.MolFromSmiles(smiles)

    if not mol:
        return {}

    mol = Chem.AddHs(mol)

    desc_names = [x[0] for x in Descriptors._descList]
    calc = MoleculeDescriptors.MolecularDescriptorCalculator(desc_names)
    desc_vals = calc.CalcDescriptors(mol)

    desc_dict = dict(zip(desc_names, desc_vals))

    for key, value in desc_dict.items():
        if value is None or (isinstance(value, float) and np.isnan(value)):
            desc_dict[key] = np.nan

    return desc_dict


def combine_features(cas_id: str) -> dict:
    """
    Retrieves SMILES, converts to QSAR-ready SMILES, and generates RDKit descriptors.
    """
    t = time.time()
    smiles = get_smiles_from_cas(cas_id)
    print(f"Total CAS-to-SMILES time: {time.time() - t:.2f} seconds", flush=True)

    if not smiles:
        raise ValueError(f"No SMILES found for CAS: {cas_id}")

    t = time.time()
    qsar_smiles = qsar_ready_smiles(smiles)
    print(f"QSAR-ready SMILES time: {time.time() - t:.2f} seconds", flush=True)

    if not qsar_smiles:
        raise ValueError(f"Could not create QSAR-ready SMILES for CAS: {cas_id}")

    t = time.time()
    rdkit_feats = generate_rdkit_features(qsar_smiles)
    print(f"RDKit descriptor time: {time.time() - t:.2f} seconds", flush=True)

    if not rdkit_feats:
        raise ValueError(f"Could not generate RDKit descriptors for CAS: {cas_id}")

    combined = {
        "CAS": cas_id,
        "SMILES": qsar_smiles,
    }

    combined.update(rdkit_feats)

    return combined


def _coerce_numeric_feature(value):
    if value is None:
        return np.nan

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return np.nan

    return numeric_value if np.isfinite(numeric_value) else np.nan


def prepare_numeric_features(combined: dict) -> np.ndarray:
    """
    Extract numeric features in the feature order saved with the model artifact.
    """
    if not FEATURE_NAMES:
        raise ValueError("Model feature names were not loaded.")

    numeric = [
        _coerce_numeric_feature(combined.get(feature))
        for feature in FEATURE_NAMES
    ]

    return np.array([numeric], dtype=float)


def impute_with_column_means(X, col_means):
    """
    Impute NaN values using training-set column means saved in the model artifact.
    """
    X_array = np.asarray(X, dtype=float).copy()
    col_means = np.asarray(col_means, dtype=float)

    missing_rows, missing_cols = np.where(np.isnan(X_array))

    if len(missing_rows) > 0:
        X_array[missing_rows, missing_cols] = col_means[missing_cols]

    return X_array


# ============================================================
# APPLICABILITY DOMAIN
# ============================================================

def evaluate_applicability_domain(X_query_imputed):
    """
    Evaluate applicability domain for one or more query chemicals.
    Uses globally pre-fitted AD_KNN_MODEL to avoid fitting KNN every request.
    """
    if AD_KNN_MODEL is None:
        raise ValueError("AD KNN model was not initialized.")

    X_query_imputed = np.asarray(X_query_imputed, dtype=float)

    descriptor_mean = np.asarray(AD_REFERENCE["descriptor_mean"], dtype=float)
    descriptor_std = np.asarray(AD_REFERENCE["descriptor_std"], dtype=float)
    feature_min = np.asarray(AD_REFERENCE["feature_min"], dtype=float)
    feature_max = np.asarray(AD_REFERENCE["feature_max"], dtype=float)

    ad_distance_threshold = float(AD_REFERENCE["ad_distance_threshold"])

    # Avoid divide-by-zero if any descriptor std is zero.
    descriptor_std_safe = np.where(descriptor_std == 0, 1.0, descriptor_std)

    X_query_scaled_for_ad = (
        (X_query_imputed - descriptor_mean) / descriptor_std_safe
    )

    query_distances, query_neighbor_indices = AD_KNN_MODEL.kneighbors(
        X_query_scaled_for_ad
    )

    query_knn_mean_distances = query_distances.mean(axis=1)
    inside_distance_ad = query_knn_mean_distances <= ad_distance_threshold

    outside_feature_range_matrix = (
        (X_query_imputed < feature_min) | (X_query_imputed > feature_max)
    )

    n_features_outside_range = outside_feature_range_matrix.sum(axis=1)

    fraction_features_outside_range = (
        n_features_outside_range / X_query_imputed.shape[1]
    )

    feature_range_warning = (
        fraction_features_outside_range > FEATURE_RANGE_WARNING_THRESHOLD
    )

    ad_status = []

    for inside_distance, range_warning in zip(
        inside_distance_ad,
        feature_range_warning,
    ):
        if inside_distance and not range_warning:
            ad_status.append("Inside AD")
        elif inside_distance and range_warning:
            ad_status.append(
                "Inside distance-based AD, but descriptor-range warning"
            )
        else:
            ad_status.append("Outside AD")

    return {
        "query_knn_mean_distances": query_knn_mean_distances,
        "query_neighbor_indices": query_neighbor_indices,
        "inside_distance_ad": inside_distance_ad,
        "n_features_outside_range": n_features_outside_range,
        "fraction_features_outside_range": fraction_features_outside_range,
        "feature_range_warning": feature_range_warning,
        "outside_feature_range_matrix": outside_feature_range_matrix,
        "ad_status": np.array(ad_status, dtype=object),
        "ad_distance_threshold": ad_distance_threshold,
    }


def assign_prediction_reliability(ad_status, max_prediction_probability):
    """
    Assign reliability based on AD status and model probability.
    """
    reliability = []

    for status, max_prob in zip(ad_status, max_prediction_probability):
        if status == "Inside AD" and max_prob >= HIGH_CONFIDENCE_THRESHOLD:
            reliability.append("High")
        elif status == "Inside AD" and max_prob >= MODERATE_CONFIDENCE_THRESHOLD:
            reliability.append("Moderate")
        else:
            reliability.append("Low")

    return np.array(reliability, dtype=object)


def get_outside_range_feature_names(outside_feature_range_row):
    """
    Return feature names that are outside the training range.
    """
    return [
        feature_name
        for feature_name, is_outside in zip(FEATURE_NAMES, outside_feature_range_row)
        if is_outside
    ]


# ============================================================
# JSON HELPERS
# ============================================================

def _json_safe(value):
    """
    Convert NumPy and non-JSON-safe values to JSON-safe Python values.
    """
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]

    if isinstance(value, (np.bool_, bool)):
        return bool(value)

    if isinstance(value, (np.integer,)):
        return int(value)

    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None

    if isinstance(value, list):
        return [_json_safe(item) for item in value]

    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]

    if isinstance(value, dict):
        return {
            key: _json_safe(item)
            for key, item in value.items()
        }

    return value


def response(status_code: int, body: dict):
    """
    Standard Lambda proxy response.
    """
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(_json_safe(body)),
    }


# ============================================================
# PREDICTION
# ============================================================

def build_prediction_payload(features):
    """
    Generate model prediction, class probabilities, AD status, and reliability.
    """
    t = time.time()
    prediction = model.predict(features)
    prediction_probabilities = model.predict_proba(features)
    print(f"Model prediction time: {time.time() - t:.2f} seconds", flush=True)

    max_prediction_probability = np.max(prediction_probabilities, axis=1)

    t = time.time()
    imputed_features = impute_with_column_means(features, TRAIN_COL_MEANS)
    ad_results = evaluate_applicability_domain(imputed_features)
    print(f"Applicability domain time: {time.time() - t:.2f} seconds", flush=True)

    prediction_reliability = assign_prediction_reliability(
        ad_status=ad_results["ad_status"],
        max_prediction_probability=max_prediction_probability,
    )

    class_probabilities = {
        f"class_{_json_safe(class_label)}": _json_safe(probability)
        for class_label, probability in zip(
            CLASS_LABELS,
            prediction_probabilities[0],
        )
    }

    return {
        "prediction": _json_safe(prediction),
        "class_probabilities": class_probabilities,
        "max_prediction_probability": _json_safe(max_prediction_probability[0]),
        "ad_status": _json_safe(ad_results["ad_status"][0]),
        "prediction_reliability": _json_safe(prediction_reliability[0]),
        "knn_mean_distance": _json_safe(
            ad_results["query_knn_mean_distances"][0]
        ),
        "ad_distance_threshold": _json_safe(
            ad_results["ad_distance_threshold"]
        ),
        "inside_distance_ad": _json_safe(
            ad_results["inside_distance_ad"][0]
        ),
        "feature_range_warning": _json_safe(
            ad_results["feature_range_warning"][0]
        ),
        "n_features_outside_training_range": _json_safe(
            ad_results["n_features_outside_range"][0]
        ),
        "fraction_features_outside_training_range": _json_safe(
            ad_results["fraction_features_outside_range"][0]
        ),
        "features_outside_training_range": get_outside_range_feature_names(
            ad_results["outside_feature_range_matrix"][0]
        ),
    }


# ============================================================
# GLOBAL MODEL LOADING
# ============================================================

print("Loading model artifact...", flush=True)
MODEL_LOAD_START = time.time()

MODEL_ARTIFACT = load_model_artifact()

if isinstance(MODEL_ARTIFACT, dict) and "error" in MODEL_ARTIFACT:
    MODEL_LOADING_ERROR = MODEL_ARTIFACT["error"]

    model = None
    FEATURE_NAMES = []
    CLASS_LABELS = []
    TRAIN_COL_MEANS = np.array([], dtype=float)
    AD_REFERENCE = {}
    FEATURE_RANGE_WARNING_THRESHOLD = 0.05
    HIGH_CONFIDENCE_THRESHOLD = 0.70
    MODERATE_CONFIDENCE_THRESHOLD = 0.50
    AD_KNN_MODEL = None

    print(
        f"Model loading failed: {MODEL_LOADING_ERROR}",
        flush=True,
    )

else:
    MODEL_LOADING_ERROR = None

    model = MODEL_ARTIFACT["model"]

    FEATURE_NAMES = [
        str(feature)
        for feature in MODEL_ARTIFACT["feature_names"]
    ]

    CLASS_LABELS = list(MODEL_ARTIFACT["class_labels"])

    TRAIN_COL_MEANS = np.asarray(
        MODEL_ARTIFACT["train_col_means"],
        dtype=float,
    )

    AD_REFERENCE = MODEL_ARTIFACT["applicability_domain"]

    FEATURE_RANGE_WARNING_THRESHOLD = float(
        MODEL_ARTIFACT.get("feature_range_warning_threshold", 0.05)
    )

    HIGH_CONFIDENCE_THRESHOLD = float(
        MODEL_ARTIFACT.get("high_confidence_threshold", 0.70)
    )

    MODERATE_CONFIDENCE_THRESHOLD = float(
        MODEL_ARTIFACT.get("moderate_confidence_threshold", 0.50)
    )

    # Pre-fit the AD nearest-neighbor model once per warm Lambda container.
    try:
        X_train_scaled_for_ad = np.asarray(
            AD_REFERENCE["training_scaled_features_for_ad"],
            dtype=float,
        )

        ad_k = int(AD_REFERENCE["ad_k_effective"])

        AD_KNN_MODEL = NearestNeighbors(
            n_neighbors=ad_k,
            metric="euclidean",
        )

        AD_KNN_MODEL.fit(X_train_scaled_for_ad)

        print(
            f"AD KNN model initialized with k={ad_k}",
            flush=True,
        )

    except Exception as e:
        AD_KNN_MODEL = None
        MODEL_LOADING_ERROR = f"AD KNN initialization error: {str(e)}"

        print(
            f"AD KNN initialization failed: {repr(e)}",
            flush=True,
        )

print(
    f"Model artifact load/init time: {time.time() - MODEL_LOAD_START:.2f} seconds",
    flush=True,
)


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(event, context):
    """
    AWS Lambda handler for single CAS prediction.

    Expected JSON body:
    {
        "cas": "100-02-7"
    }
    """
    request_start = time.time()

    print("Lambda request started", flush=True)

    # Handle CORS preflight.
    if event.get("httpMethod") == "OPTIONS":
        return response(200, {"message": "CORS preflight OK"})

    # 1. Early model-load error.
    if MODEL_LOADING_ERROR or model is None:
        return response(
            500,
            {
                "error": f"Model loading error: {MODEL_LOADING_ERROR}"
            },
        )

    if not hasattr(model, "predict") or not hasattr(model, "predict_proba"):
        return response(
            500,
            {
                "error": "Loaded model has no predict/predict_proba methods"
            },
        )

    # 2. Parse input.
    try:
        payload = event.get("body")

        if isinstance(payload, str):
            data = json.loads(payload)
        elif isinstance(payload, dict):
            data = payload
        else:
            data = event

        cas = (
            data.get("cas")
            or data.get("CAS")
            or data.get("cas_number")
            or data.get("value")
        )

        if not cas:
            return response(
                400,
                {
                    "error": "Invalid input: missing CAS number. Expected key: 'cas'."
                },
            )

        cas = _normalize_cas(str(cas))

        print(f"Received CAS: {cas}", flush=True)

        if not _CAS_RE.match(cas):
            return response(
                400,
                {
                    "error": f"Invalid CAS format: {cas}"
                },
            )

    except Exception as e:
        return response(
            400,
            {
                "error": f"Invalid input: {str(e)}"
            },
        )

    # 3. Combine features.
    try:
        t = time.time()
        combined = combine_features(cas)

        print(
            f"combine_features total time: {time.time() - t:.2f} seconds",
            flush=True,
        )

    except ValueError as e:
        return response(
            400,
            {
                "error": str(e)
            },
        )

    except (HTTPError, URLError, TimeoutError, socket.timeout) as e:
        return response(
            504,
            {
                "error": (
                    "CAS-to-SMILES lookup timed out or external chemical lookup "
                    "service was unavailable. Please try again, or try another CAS number."
                ),
                "details": str(e),
            },
        )

    except Exception as e:
        print(f"Feature generation error: {repr(e)}", flush=True)

        return response(
            500,
            {
                "error": f"Feature generation error: {str(e)}"
            },
        )

    # 4. Predict.
    try:
        t = time.time()

        features = prepare_numeric_features(combined)
        prediction_payload = build_prediction_payload(features)

        print(
            f"Prediction pipeline total time: {time.time() - t:.2f} seconds",
            flush=True,
        )

    except Exception as e:
        print(f"Prediction error: {repr(e)}", flush=True)

        return response(
            500,
            {
                "error": f"Prediction error: {str(e)}"
            },
        )

    # 5. Success.
    output = {
        **prediction_payload,
        "dataset": combined,
    }

    total_time = time.time() - request_start

    print(
        f"Lambda request completed successfully in {total_time:.2f} seconds",
        flush=True,
    )

    return response(200, output)
