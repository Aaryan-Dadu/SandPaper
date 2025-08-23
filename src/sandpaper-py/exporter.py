import pandas as pd

def export_groups(data_dict: dict, required_encoding, output_file):
    # Step 1: Find the longest list (number of rows)
    max_len = max(len(v) for v in data_dict.values())

    # Step 2: Pad all lists to the same length
    normalized = {}
    for key, values in data_dict.items():
        padded = values + [""] * (max_len - len(values))  # pad with empty string
        normalized[key] = padded

    # Step 3: Convert to DataFrame and export
    df = pd.DataFrame(normalized)

    df.to_csv(output_file, index=False, encoding=required_encoding)
    # print(f"Saved to {output_file}")
