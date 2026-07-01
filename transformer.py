import json
import argparse
import re
from collections import defaultdict

# --- Utility Functions ---
def clean_phone_number(raw_phone):
    """Strip everything but digits and add E.164 country code."""
    if not raw_phone: 
        return None
    digits_only = re.sub(r'\D', '', raw_phone)
    # assume US +1 if 10 digits
    return f"+1{digits_only}" if len(digits_only) == 10 else f"+{digits_only}"

def format_skill_tag(skill_string):
    return skill_string.strip().lower()

# --- Data Parsers ---
def load_structured_json(filepath):
    """Parse ATS export. High trust score (0.9)."""
    parsed_records = []
    try:
        with open(filepath, 'r') as file:
            raw_data = json.load(file)
            for row in raw_data:
                # Use email as the main ID for merging later
                contact_email = row.get("contact_email")
                primary_id = contact_email if contact_email else str(row.get("id", ""))
                
                record = {
                    "candidate_id": primary_id, 
                    "full_name": row.get("name"),
                    "emails": [contact_email] if contact_email else [],
                    "phones": [clean_phone_number(row.get("phone"))] if row.get("phone") else [],
                    "skills": [format_skill_tag(s) for s in row.get("tags", [])],
                    "source": "ATS_JSON",
                    "trust_score": 0.9
                }
                parsed_records.append(record)
    except Exception as e:
        print(f"Failed to read JSON: {e}")
    return parsed_records

def parse_txt_notes(filepath):
    """Scrape unstructured notes. Lower trust score (0.6)."""
    parsed_records = []
    try:
        with open(filepath, 'r') as file:
            content = file.read()
            
            # basic regex patterns
            found_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', content)
            found_phones = re.findall(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', content)
            
            record = {
                "candidate_id": found_emails[0] if found_emails else "unknown", 
                "full_name": None, # let the JSON handle the name
                "emails": found_emails,
                "phones": [clean_phone_number(p) for p in found_phones],
                "source": "RECRUITER_NOTES",
                "trust_score": 0.6
            }
            parsed_records.append(record)
    except Exception as e:
         print(f"Failed to read TXT: {e}")
    return parsed_records

# --- Core Merge Logic ---
def unify_candidate_profiles(all_records):
    """Group by candidate_id and merge fields based on trust scores."""
    # auto-initialize sets for deduplication
    candidate_map = defaultdict(lambda: {
        "emails": set(), "phones": set(), "skills": set(), "provenance": {}
    })
    
    for record in all_records:
        cid = record.get("candidate_id")
        if not cid: 
            continue
        
        existing_profile = candidate_map[cid]
        current_source = record["source"]
        current_score = record["trust_score"]
        
        # 1. Overwrite scalar fields if this source is more reliable
        for field in ["full_name", "headline", "years_experience"]:
            if record.get(field):
                prev_score = existing_profile.get("provenance", {}).get(field, {}).get("confidence", 0)
                if current_score > prev_score:
                    existing_profile[field] = record[field]
                    existing_profile["provenance"][field] = {"source": current_source, "confidence": current_score}
                    
        # 2. Union array fields to keep all unique data points
        for field in ["emails", "phones", "skills"]:
            for item in record.get(field, []):
                if item:
                    existing_profile[field].add(item)
                    existing_profile["provenance"][f"{field}[{item}]"] = {"source": current_source, "confidence": current_score}

    # Cast sets back to lists so json.dumps doesn't crash
    for cid, profile_data in candidate_map.items():
        profile_data["candidate_id"] = cid
        profile_data["emails"] = list(profile_data["emails"])
        profile_data["phones"] = list(profile_data["phones"])
        profile_data["skills"] = list(profile_data["skills"])
        
    return list(candidate_map.values())

# --- Projection Engine ---
def fetch_nested_value(data_dict, key_path):
    """Extract array values like emails[0] safely."""
    try:
        if "[" in key_path and "]" in key_path:
            base_key, idx = key_path.replace("]", "").split("[")
            return data_dict.get(base_key, [])[int(idx)]
        return data_dict.get(key_path)
    except (IndexError, TypeError, KeyError):
        return None

def reshape_output(unified_profile, schema_config):
    """Map the master profile to the requested runtime config."""
    final_dict = {}
    missing_strategy = schema_config.get("on_missing", "null")
    
    for rule in schema_config.get("fields", []):
        target_name = rule["path"]
        source_name = rule.get("from", target_name)
        
        extracted_val = fetch_nested_value(unified_profile, source_name)
        
        if extracted_val is None:
            if rule.get("required"):
                if missing_strategy == "error":
                    raise ValueError(f"CRITICAL: Missing required field {target_name}")
                elif missing_strategy == "omit":
                    continue
            final_dict[target_name] = None if missing_strategy == "null" else None
        else:
            final_dict[target_name] = extracted_val
            
    if schema_config.get("include_confidence", False):
        final_dict["provenance"] = unified_profile.get("provenance")
        
    return final_dict

# --- CLI Setup ---
if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Merge candidate data from multiple sources.")
    cli.add_argument("--json", help="Path to structured ATS JSON file")
    cli.add_argument("--txt", help="Path to unstructured notes file")
    cli.add_argument("--config", help="Path to runtime config JSON", required=True)
    args = cli.parse_args()

    # Step 1: Parse
    raw_extractions = []
    if args.json:
        raw_extractions.extend(load_structured_json(args.json))
    if args.txt:
         raw_extractions.extend(parse_txt_notes(args.txt))

    # Step 2: Merge
    master_profiles = unify_candidate_profiles(raw_extractions)

    # Step 3: Project Configuration
    with open(args.config, 'r') as config_file:
        user_config = json.load(config_file)

    output_payload = []
    for profile in master_profiles:
        try:
            output_payload.append(reshape_output(profile, user_config))
        except ValueError as err:
            print(f"Skipping a profile: {err}")

    # Print final JSON to terminal
    print(json.dumps(output_payload, indent=2))