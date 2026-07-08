import json
import torch
import os
import sys
import numpy as np
from rdkit import Chem
from rdkit.Chem import Descriptors
from rdkit.ML.Descriptors import MoleculeDescriptors
import json
import re
import time
import sklearn
import sklearn.ensemble
import sklearn.impute
import sklearn.linear_model
import sklearn.pipeline
import sklearn.preprocessing
import sklearn.svm
import sklearn.tree
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import csv
import io
import boto3
from sklearn.neighbors import NearestNeighbors

# --- CORS HEADER ---
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json"
}

UPLOAD_BUCKET = 'toxprojectbucket'
REGION        = os.environ.get('AWS_REGION', 'us-east-2')
s3_client     = boto3.client('s3', region_name=REGION)

# --- Helper Functions ---

MODEL_ARTIFACT_NAME = "best_voting_model_panelb_with_AD.pt"
REQUIRED_ARTIFACT_KEYS = {
    "model",
    "feature_names",
    "class_labels",
    "train_col_means",
    "applicability_domain",
}


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
                map_location="cpu",
                weights_only=False,
            )
        except TypeError:
            artifact = torch.load(model_path, map_location="cpu")

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

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
CACTUS  = "https://cactus.nci.nih.gov/chemical/structure"

_CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")

def _normalize_cas(cas: str) -> str:
    s = (cas or "").strip()
    # normalize non-ASCII hyphens
    return (s.replace("\u2010", "-")
             .replace("\u2011", "-")
             .replace("\u2012", "-")
             .replace("\u2013", "-")
             .replace("\u2212", "-"))

def _http_get(url: str, timeout: int = 500) -> bytes:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()

def _http_get_json(url: str, timeout: int = 500) -> dict:
    raw = _http_get(url, timeout=timeout)
    return json.loads(raw.decode("utf-8"))

def _http_get_text(url: str, timeout: int = 500) -> str:
    raw = _http_get(url, timeout=timeout)
    return raw.decode("utf-8").strip()

def _retry(fn, tries: int = 2, delay: float = 0.4):
    last = None
    for _ in range(tries):
        try:
            return fn()
        except (HTTPError, URLError) as e:
            last = e
            time.sleep(delay)
    if last:
        raise last

# --- CID/SID resolution using CAS as a Registry Number (RN) ---

def _pubchem_cids_by_rn(cas_rn: str):
    # Precise: CAS as a registry number (RN), not a free-text "name"
    url = f"{PUBCHEM}/compound/xref/RN/{cas_rn}/cids/JSON"
    data = _retry(lambda: _http_get_json(url))
    # If a Fault is returned, no IdentifierList will be present
    ids = data.get("IdentifierList", {}).get("CID", [])
    return ids

def _pubchem_cid_via_sid_rn(cas_rn: str):
    # Some records exist only as Substances. Map SID -> CID.
    url_sids = f"{PUBCHEM}/substance/xref/RN/{cas_rn}/sids/JSON"
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
    # Ask for both Canonical and Isomeric so we have options
    url = f"{PUBCHEM}/compound/cid/{cid}/property/CanonicalSMILES,IsomericSMILES/JSON"
    data = _retry(lambda: _http_get_json(url))
    # If the response is a Fault, there will be no PropertyTable
    props = data.get("PropertyTable", {}).get("Properties", [])
    if not props:
        return None
    entry = props[0]
    # Prefer canonical; fall back to isomeric if needed
    return entry.get("CanonicalSMILES") or entry.get("IsomericSMILES")

def _cactus_smiles(identifier: str) -> str | None:
    # NIH Cactus returns plain text; "Not Found" in body if missing
    url = f"{CACTUS}/{identifier}/smiles"
    try:
        txt = _retry(lambda: _http_get_text(url))
        return None if (not txt or "Not Found" in txt) else txt
    except (HTTPError, URLError):
        return None

def get_smiles_from_cas(cas_number: str) -> str | None:
    """
    Resolve SMILES from a CAS number without PubChemPy.
    Order: PubChem by RN -> PubChem SID->CID -> NIH Cactus.
    Returns None if not found anywhere.
    Raises HTTPError/URLError only if both resolvers are unreachable.
    """
    cas = _normalize_cas(cas_number)
    if not _CAS_RE.match(cas):
        raise ValueError(f"Invalid CAS format: {cas!r}")

    # 1) PubChem: CAS RN -> CID(s)
    try:
        cids = _pubchem_cids_by_rn(cas)
        cid = cids[0] if cids else _pubchem_cid_via_sid_rn(cas)
        if cid:
            smi = _pubchem_smiles_from_cid(cid)
            if smi:
                return smi
    except (HTTPError, URLError):
        # If PubChem is unreachable, try Cactus before re-raising
        smi = _cactus_smiles(cas)
        if smi:
            return smi
        raise

    # 2) Fallback to Cactus even if PubChem was reachable but had no match
    return _cactus_smiles(cas)


def qsar_ready_smiles(smiles: str) -> str:
    """
    Converts a SMILES string into a QSAR-ready version (canonical, without stereochemistry).
    """
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol:
            return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=False)
        else:
            return None
    except Exception:
        return None

def generate_rdkit_features(smiles: str) -> dict:
    """
    Generate RDKit-based molecular descriptors for a single molecule given its SMILES.
    Missing descriptor values are preserved as NaN for the trained imputer.
    """
    mol = Chem.MolFromSmiles(smiles)
    if not mol:
        return {}
    mol = Chem.AddHs(mol)
    descNames = [x[0] for x in Descriptors._descList]
    calc = MoleculeDescriptors.MolecularDescriptorCalculator(descNames)
    desc_vals = calc.CalcDescriptors(mol)
    desc_dict = dict(zip(descNames, desc_vals))
    
    # Preserve missing values for the model's trained mean imputer.
    for key, value in desc_dict.items():
        if value is None or (isinstance(value, float) and np.isnan(value)):
            desc_dict[key] = np.nan
    return desc_dict

def combine_features(cas_id: str) -> dict:
    """
    Combines features for a given chemical: retrieves SMILES, converts it to QSAR-ready form,
    computes logBCF, and adds RDKit descriptors.
    """
    smiles = get_smiles_from_cas(cas_id)
    if not smiles:
        raise ValueError(f"No SMILES found for CAS: {cas_id}")
    qsar_smiles = qsar_ready_smiles(smiles)
    rdkit_feats = generate_rdkit_features(qsar_smiles)
    combined = {
        "CAS": cas_id,
        "SMILES": qsar_smiles
    }
    combined.update(rdkit_feats)
    return combined

def prepare_numeric_features(combined: dict) -> np.ndarray:
    """
    Extracts numeric features in the feature order saved with the model artifact.
    """
    if not FEATURE_NAMES:
        raise ValueError("Model feature names were not loaded.")

    numeric = [_coerce_numeric_feature(combined.get(feature)) for feature in FEATURE_NAMES]
    return np.array([numeric], dtype=float)


def _coerce_numeric_feature(value):
    if value is None:
        return np.nan

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return np.nan

    return numeric_value if np.isfinite(numeric_value) else np.nan


def impute_with_column_means(X, col_means):
    X_array = np.asarray(X, dtype=float).copy()
    missing_rows, missing_cols = np.where(np.isnan(X_array))
    X_array[missing_rows, missing_cols] = col_means[missing_cols]
    return X_array


def evaluate_applicability_domain(X_query_imputed):
    X_query_imputed = np.asarray(X_query_imputed, dtype=float)

    descriptor_mean = np.asarray(AD_REFERENCE["descriptor_mean"], dtype=float)
    descriptor_std = np.asarray(AD_REFERENCE["descriptor_std"], dtype=float)
    feature_min = np.asarray(AD_REFERENCE["feature_min"], dtype=float)
    feature_max = np.asarray(AD_REFERENCE["feature_max"], dtype=float)
    X_train_scaled_for_ad = np.asarray(
        AD_REFERENCE["training_scaled_features_for_ad"],
        dtype=float,
    )
    ad_k = int(AD_REFERENCE["ad_k_effective"])
    ad_distance_threshold = float(AD_REFERENCE["ad_distance_threshold"])

    X_query_scaled_for_ad = (X_query_imputed - descriptor_mean) / descriptor_std

    knn_query = NearestNeighbors(
        n_neighbors=ad_k,
        metric="euclidean",
    )
    knn_query.fit(X_train_scaled_for_ad)

    query_distances, query_neighbor_indices = knn_query.kneighbors(
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
            ad_status.append("Inside distance-based AD, but descriptor-range warning")
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
    return [
        feature_name
        for feature_name, is_outside in zip(FEATURE_NAMES, outside_feature_range_row)
        if is_outside
    ]


def _json_safe(value):
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
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def build_prediction_payload(features):
    prediction = model.predict(features)
    prediction_probabilities = model.predict_proba(features)
    max_prediction_probability = np.max(prediction_probabilities, axis=1)

    imputed_features = impute_with_column_means(features, TRAIN_COL_MEANS)
    ad_results = evaluate_applicability_domain(imputed_features)
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
        "knn_mean_distance": _json_safe(ad_results["query_knn_mean_distances"][0]),
        "ad_distance_threshold": _json_safe(ad_results["ad_distance_threshold"]),
        "inside_distance_ad": _json_safe(ad_results["inside_distance_ad"][0]),
        "feature_range_warning": _json_safe(ad_results["feature_range_warning"][0]),
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

# --- Global Model Loading ---
# Loading the model globally helps reuse it across Lambda invocations.
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
else:
    MODEL_LOADING_ERROR = None
    model = MODEL_ARTIFACT["model"]
    FEATURE_NAMES = [str(feature) for feature in MODEL_ARTIFACT["feature_names"]]
    CLASS_LABELS = list(MODEL_ARTIFACT["class_labels"])
    TRAIN_COL_MEANS = np.asarray(MODEL_ARTIFACT["train_col_means"], dtype=float)
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


def lambda_handler(event, context):
    # 0) Early model-load error
    if MODEL_LOADING_ERROR or model is None:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": f"Model loading error: {MODEL_LOADING_ERROR}"})
        }
    if not hasattr(model, "predict") or not hasattr(model, "predict_proba"):
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "Loaded model has no predict/predict_proba methods"})
        }

    # 1) Parse input
    try:
        body = event.get("body")
        data = json.loads(body) if isinstance(body, str) else event
        s3Key = data["s3Key"]
    except Exception as e:
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": f"Invalid input: {e}"})
        }

    # 2) Download CSV from S3
    try:
        resp = s3_client.get_object(Bucket=UPLOAD_BUCKET, Key=s3Key)
        csv_bytes = resp['Body'].read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(csv_bytes))
    except Exception as e:
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": f"Could not load CSV: {e}"})
        }

    # 3) Validate headers & missing values
    required = {"CAS"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "error": f"CSV must have headers: {', '.join(required)}"
            })
        }

    rows = list(reader)
    if not rows:
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "CSV is empty"})
        }

    # check for any empty cells
    for i,row in enumerate(rows, start=1):
        for col,val in row.items():
            if val is None or val.strip()=="":
                return {
                    "statusCode": 400,
                    "headers": CORS_HEADERS,
                    "body": json.dumps({
                        "error": f"Missing value at row {i}, column '{col}'"
                    })
                }

    # 4) Process each row
    results = []
    for row in rows:
        cas_id = row["CAS"].strip()

        try:
            combined = combine_features(cas_id)
            features = prepare_numeric_features(combined)
            results.append({
                "CAS": cas_id,
                "dataset": combined,
                **build_prediction_payload(features),
            })
        except Exception as e:
            return {
                "statusCode": 500,
                "headers": CORS_HEADERS,
                "body": json.dumps({
                    "error": f"Error processing CAS {cas_id}: {e}"
                })
            }

    # 5) Return everything
    return {
        "statusCode": 200,
        "headers": CORS_HEADERS,
        "body": json.dumps(_json_safe({ "results": results }))
    }
