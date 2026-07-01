import json
import argparse
import re
from collections import defaultdict

# --- 1. NORMALIZATION UTILS ---
def normalize_phone(phone_str):
    """Naive E.164 normalization for demonstration."""
    if not phone_str: return None
    digits = re.sub(r'\D', '', phone_str)
    return f"+1{digits}" if len(digits) == 10 else f"+{digits}"

def normalize_skill(skill_str):
    return skill_str.strip().lower()

# --- 2. EXTRACTORS ---
def extract_ats_json(filepath):
    """Extracts from structured JSON. High confidence (0.9)."""
    profiles = []
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
            for item in data:
                # FIX: Prioritize email as the universal merge key
                email = item.get("contact_email")
                merge_id = email if email else str(item.get("id", ""))
                
                profile = {
                    "candidate_id": merge_id, 
                    "full_name": item.get("name"),
                    "emails": [email] if email else [],
                    "phones": [normalize_phone(item.get("phone"))] if item.get("phone") else [],
                    "skills": [normalize_skill(s) for s in item.get("tags", [])],
                    "source": "ATS_JSON",
                    "confidence": 0.9
                }
                profiles.append(profile)
    except Exception as e:
        print(f"Error reading JSON: {e}")
    return profiles

def extract_recruiter_notes(filepath):
    """Extracts from unstructured TXT using regex. Lower confidence (0.6)."""
    profiles = []
    try:
        with open(filepath, 'r') as f:
            text = f.read()
            # Extremely basic regex for demonstration
            emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
            phones = re.findall(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', text)
            
            profile = {
                "candidate_id": emails[0] if emails else "unknown", # Uses email as ID
                "full_name": None, 
                "emails": emails,
                "phones": [normalize_phone(p) for p in phones],
                "source": "RECRUITER_NOTES",
                "confidence": 0.6
            }
            profiles.append(profile)
    except Exception as e:
         print(f"Error reading TXT: {e}")
    return profiles

# --- 3. MERGE ENGINE ---
def merge_profiles(profiles):
    """Merges partial profiles into canonical records using confidence scores."""
    merged_data = defaultdict(lambda: {
        "emails": set(), "phones": set(), "skills": set(), "provenance": {}
    })
    
    for p in profiles:
        cid = p.get("candidate_id")
        if not cid: continue
        
        target = merged_data[cid]
        source_name = p["source"]
        conf = p["confidence"]
        
        # Merge single-value fields (take highest confidence)
        for field in ["full_name", "headline", "years_experience"]:
            if p.get(field):
                current_conf = target.get("provenance", {}).get(field, {}).get("confidence", 0)
                if conf > current_conf:
                    target[field] = p[field]
                    target["provenance"][field] = {"source": source_name, "confidence": conf}
                    
        # Merge arrays (Union)
        for field in ["emails", "phones", "skills"]:
            for item in p.get(field, []):
                if item:
                    target[field].add(item)
                    target["provenance"][f"{field}[{item}]"] = {"source": source_name, "confidence": conf}

    # Convert sets back to lists for JSON serialization
    for cid, data in merged_data.items():
        data["candidate_id"] = cid
        data["emails"] = list(data["emails"])
        data["phones"] = list(data["phones"])
        data["skills"] = list(data["skills"])
        
    return list(merged_data.values())

# --- 4. PROJECTION LAYER (THE TWIST) ---
def resolve_path(data, path):
    """Helper to extract nested/array data like 'emails[0]'"""
    try:
        if "[" in path and "]" in path:
            base, index = path.replace("]", "").split("[")
            return data.get(base, [])[int(index)]
        return data.get(path)
    except (IndexError, TypeError, KeyError):
        return None

def apply_projection(canonical_profile, config):
    """Reshapes the output based on runtime config."""
    projected = {}
    on_missing = config.get("on_missing", "null")
    
    for field_def in config.get("fields", []):
        target_key = field_def["path"]
        source_key = field_def.get("from", target_key)
        
        val = resolve_path(canonical_profile, source_key)
        
        if val is None:
            if field_def.get("required"):
                if on_missing == "error":
                    raise ValueError(f"Required field {target_key} is missing.")
                elif on_missing == "omit":
                    continue
            projected[target_key] = None if on_missing == "null" else None
        else:
            projected[target_key] = val
            
    if config.get("include_confidence", False):
        projected["provenance"] = canonical_profile.get("provenance")
        
    return projected

# --- 5. CLI INTERFACE ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Source Candidate Transformer")
    parser.add_argument("--json", help="Path to ATS JSON source")
    parser.add_argument("--txt", help="Path to Recruiter Notes source")
    parser.add_argument("--config", help="Path to projection config JSON", required=True)
    args = parser.parse_args()

    # 1. Ingest & Extract
    all_profiles = []
    if args.json:
        all_profiles.extend(extract_ats_json(args.json))
    if args.txt:
         all_profiles.extend(extract_recruiter_notes(args.txt))

    # 2. Merge
    canonical_profiles = merge_profiles(all_profiles)

    # 3. Project & Output
    with open(args.config, 'r') as f:
        config = json.load(f)

    final_output = []
    for profile in canonical_profiles:
        try:
            final_output.append(apply_projection(profile, config))
        except ValueError as e:
            print(f"Skipping profile due to error: {e}")

    print(json.dumps(final_output, indent=2))