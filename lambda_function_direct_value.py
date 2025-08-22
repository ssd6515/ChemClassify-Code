import json
import torch
import os
import numpy as np
from rdkit import Chem
from rdkit.Chem import Descriptors
from rdkit.ML.Descriptors import MoleculeDescriptors
import sklearn
import sklearn.ensemble
import sklearn.tree
import json
import re
import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

# --- CORS HEADER ---
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json"
}

# --- Helper Functions ---

def load_model():
    """
    Loads the pre-trained Gradient Boosting model from best_gbdt_model.pt.
    """
    model_path = os.path.join(os.path.dirname(__file__), 'best_gbdt_model_now.pt')
    try:
        model = torch.load(model_path, map_location=torch.device("cpu"), weights_only=False)
        return model
    except Exception as e:
        return {"error": f"Error loading model: {str(e)}"}

def compute_logBCF(logKOW: float) -> float:
    """
    Computes logBCF from logKOW using a piecewise formula.
    """
    if logKOW < 1:
        return 0.15
    elif logKOW <= 6:
        return 0.85 * logKOW - 0.70
    elif logKOW < 10:
        return -0.20 * (logKOW ** 2) + 2.74 * logKOW - 4.72
    else:
        return 2.68



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

def _http_get(url: str, timeout: int = 6) -> bytes:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()

def _http_get_json(url: str, timeout: int = 6) -> dict:
    raw = _http_get(url, timeout=timeout)
    return json.loads(raw.decode("utf-8"))

def _http_get_text(url: str, timeout: int = 6) -> str:
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
    Missing descriptor values are replaced with 0.0.
    """
    mol = Chem.MolFromSmiles(smiles)
    if not mol:
        return {}
    mol = Chem.AddHs(mol)
    descNames = [x[0] for x in Descriptors._descList]
    calc = MoleculeDescriptors.MolecularDescriptorCalculator(descNames)
    desc_vals = calc.CalcDescriptors(mol)
    desc_dict = dict(zip(descNames, desc_vals))
    
    # Replace missing values with 0.0
    for key, value in desc_dict.items():
        if value is None or (isinstance(value, float) and np.isnan(value)):
            desc_dict[key] = 0.0
    return desc_dict

def combine_features(cas_id: str, logKOW: float) -> dict:
    """
    Combines features for a given chemical: retrieves SMILES, converts it to QSAR-ready form,
    computes logBCF, and adds RDKit descriptors.
    """
    smiles = get_smiles_from_cas(cas_id)
    if not smiles:
        raise ValueError(f"No SMILES found for CAS: {cas_id}")
    qsar_smiles = qsar_ready_smiles(smiles)
    logBCF_value = compute_logBCF(logKOW)
    rdkit_feats = generate_rdkit_features(qsar_smiles)
    combined = {
        "CAS": cas_id,
        "logBCF": logBCF_value,
        "logKOW": logKOW,
        "SMILES": qsar_smiles
    }
    combined.update(rdkit_feats)
    return combined

def prepare_numeric_features(combined: dict) -> np.ndarray:
    """
    Extracts numeric features in the specific order expected by the model.
    """
    feature_order = [
        "logBCF", "logKOW", "MaxAbsEStateIndex", "MaxEStateIndex", "MinAbsEStateIndex", "MinEStateIndex",
        "qed", "SPS", "MolWt", "HeavyAtomMolWt", "ExactMolWt", "NumValenceElectrons", "NumRadicalElectrons",
        "MaxPartialCharge", "MinPartialCharge", "MaxAbsPartialCharge", "MinAbsPartialCharge",
        "FpDensityMorgan1", "FpDensityMorgan2", "FpDensityMorgan3", "BCUT2D_MWHI", "BCUT2D_MWLOW",
        "BCUT2D_CHGHI", "BCUT2D_CHGLO", "BCUT2D_LOGPHI", "BCUT2D_LOGPLOW", "BCUT2D_MRHI", "BCUT2D_MRLOW",
        "AvgIpc", "BalabanJ", "BertzCT", "Chi0", "Chi0n", "Chi0v", "Chi1", "Chi1n", "Chi1v", "Chi2n", "Chi2v",
        "Chi3n", "Chi3v", "Chi4n", "Chi4v", "HallKierAlpha", "Ipc", "Kappa1", "Kappa2", "Kappa3", "LabuteASA",
        "PEOE_VSA1", "PEOE_VSA10", "PEOE_VSA11", "PEOE_VSA12", "PEOE_VSA13", "PEOE_VSA14", "PEOE_VSA2",
        "PEOE_VSA3", "PEOE_VSA4", "PEOE_VSA5", "PEOE_VSA6", "PEOE_VSA7", "PEOE_VSA8", "PEOE_VSA9",
        "SMR_VSA1", "SMR_VSA10", "SMR_VSA2", "SMR_VSA3", "SMR_VSA4", "SMR_VSA5", "SMR_VSA6", "SMR_VSA7",
        "SMR_VSA9", "SlogP_VSA1", "SlogP_VSA10", "SlogP_VSA11", "SlogP_VSA12", "SlogP_VSA2", "SlogP_VSA3",
        "SlogP_VSA4", "SlogP_VSA5", "SlogP_VSA6", "SlogP_VSA7", "SlogP_VSA8", "TPSA", "EState_VSA1", "EState_VSA10",
        "EState_VSA11", "EState_VSA2", "EState_VSA3", "EState_VSA4", "EState_VSA5", "EState_VSA6", "EState_VSA7",
        "EState_VSA8", "EState_VSA9", "VSA_EState1", "VSA_EState10", "VSA_EState2", "VSA_EState3", "VSA_EState4",
        "VSA_EState5", "VSA_EState6", "VSA_EState7", "VSA_EState8", "VSA_EState9", "FractionCSP3", "HeavyAtomCount",
        "NHOHCount", "NOCount", "NumAliphaticCarbocycles", "NumAliphaticHeterocycles", "NumAliphaticRings",
        "NumAmideBonds", "NumAromaticCarbocycles", "NumAromaticHeterocycles", "NumAromaticRings",
        "NumAtomStereoCenters", "NumBridgeheadAtoms", "NumHAcceptors", "NumHDonors", "NumHeteroatoms",
        "NumHeterocycles", "NumRotatableBonds", "NumSaturatedCarbocycles", "NumSaturatedHeterocycles",
        "NumSaturatedRings", "NumUnspecifiedAtomStereoCenters", "Phi", "RingCount", "MolLogP", "MolMR",
        "fr_Al_COO", "fr_Al_OH", "fr_Al_OH_noTert", "fr_ArN", "fr_Ar_COO", "fr_Ar_N", "fr_Ar_NH", "fr_Ar_OH",
        "fr_COO", "fr_COO2", "fr_C_O", "fr_C_O_noCOO", "fr_C_S", "fr_Imine", "fr_NH0", "fr_NH1", "fr_NH2",
        "fr_N_O", "fr_Ndealkylation1", "fr_Ndealkylation2", "fr_Nhpyrrole", "fr_SH", "fr_aldehyde",
        "fr_alkyl_carbamate", "fr_alkyl_halide", "fr_allylic_oxid", "fr_amide", "fr_amidine", "fr_aniline",
        "fr_aryl_methyl", "fr_benzene", "fr_bicyclic", "fr_ester", "fr_ether", "fr_furan", "fr_guanido",
        "fr_halogen", "fr_hdrzine", "fr_hdrzone", "fr_imidazole", "fr_imide", "fr_ketone", "fr_ketone_Topliss",
        "fr_lactone", "fr_methoxy", "fr_morpholine", "fr_nitrile", "fr_nitro", "fr_nitro_arom", "fr_nitroso",
        "fr_oxazole", "fr_oxime", "fr_para_hydroxylation", "fr_phenol", "fr_phenol_noOrthoHbond", "fr_phos_acid",
        "fr_phos_ester", "fr_piperdine", "fr_piperzine", "fr_priamide", "fr_pyridine", "fr_sulfide",
        "fr_sulfonamd", "fr_sulfone", "fr_term_acetylene", "fr_thiazole", "fr_thiocyan", "fr_thiophene",
        "fr_urea"
    ]
    
    numeric = []
    missing_features = []
    for feature in feature_order:
        if feature in combined:
            numeric.append(combined[feature])
        else:
            missing_features.append(feature)
    if missing_features:
        raise KeyError(f"The following required features are missing: {missing_features}")
    return np.array([numeric])

# --- Global Model Loading ---
# Loading the model globally helps reuse it across Lambda invocations.
model = load_model()
if isinstance(model, dict) and "error" in model:
    MODEL_LOADING_ERROR = model["error"]
else:
    MODEL_LOADING_ERROR = None

def lambda_handler(event, context):
    # 1) Early model‑load error
    if MODEL_LOADING_ERROR:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": f"Model loading error: {MODEL_LOADING_ERROR}"})
        }

    # 2) Parse input
    try:
        payload = event.get("body")
        data = json.loads(payload) if isinstance(payload, str) else event
        cas = data["cas"]
        logKOW = float(data["logKOW"])
    except Exception as e:
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": f"Invalid input: {str(e)}"})
        }

    # 3) Combine features
    try:
        combined = combine_features(cas, logKOW)
    except Exception as e:
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)})
        }

    # 4) Predict
    try:
        features = prepare_numeric_features(combined)
        tensor = torch.tensor(features, dtype=torch.float)
        prediction = model.predict(tensor)
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": f"Prediction error: {str(e)}"})
        }

    # 5) Success
    output = {
        "prediction": prediction.tolist() if hasattr(prediction, "tolist") else prediction,
        "dataset": combined
    }
    return {
        "statusCode": 200,
        "headers": CORS_HEADERS,
        "body": json.dumps(output)
    }