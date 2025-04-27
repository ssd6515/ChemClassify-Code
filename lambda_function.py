import json
import torch
import os
import numpy as np
from rdkit import Chem
from rdkit.Chem import Descriptors
from rdkit.ML.Descriptors import MoleculeDescriptors
import pubchempy as pcp
import csv
import io
import boto3

# --- CORS HEADER ---
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json"
}

UPLOAD_BUCKET = 'toxprojectbucket'
REGION        = os.environ.get('AWS_REGION', 'us-east-2')
s3_client     = boto3.client('s3', region_name=REGION)

# --- Helper Functions ---
# global placeholder for your model
MODEL = None

def get_model():
    global MODEL
    if MODEL is None:
        # only import torch (and load your model) when you actually need it
        model_path = os.path.join(os.path.dirname(__file__), 'best_gbdt_model_now.pt')
        try:
            MODEL = torch.load(model_path, map_location=torch.device("cpu"), weights_only=False)
            return MODEL
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

def get_smiles_from_cas(cas_id: str) -> str:
    """
    Retrieves the SMILES string for a given CAS number using PubChem.
    """
    try:
        compounds = pcp.get_compounds(cas_id, 'name')
        if compounds:
            return compounds[0].canonical_smiles
        else:
            return None
    except Exception:
        return None

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


def lambda_handler(event, context):
    model = get_model()
    if isinstance(model, dict) and "error" in model:
        MODEL_LOADING_ERROR = model["error"]
    else:
        MODEL_LOADING_ERROR = None
    # 0) Early model‑load error
    if MODEL_LOADING_ERROR:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": f"Model loading error: {MODEL_LOADING_ERROR}"})
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
    required = {"CAS", "logKOW"}
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
            logKOW_val = float(row["logKOW"])
        except:
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({
                    "error": f"Invalid logKOW '{row['logKOW']}' for CAS {cas_id}"
                })
            }

        try:
            combined = combine_features(cas_id, logKOW_val)
            features = prepare_numeric_features(combined)
            tensor   = torch.tensor(features, dtype=torch.float)
            pred     = model.predict(tensor)
            # If sklearn array:
            output_pred = pred.tolist() if hasattr(pred, "tolist") else pred
            results.append({
                "CAS": cas_id,
                "logKOW": logKOW_val,
                "dataset": combined,
                "prediction": output_pred
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
        "body": json.dumps({ "results": results })
    }