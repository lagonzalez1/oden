"""
Embed company descriptions and committee jurisdiction texts, score every
ticker against every committee by cosine similarity, and write out a
Cytoscape `elements` array — drop the output straight into your Graph
component's `elements` prop.

Run after fetch_company_data.py (produces companies.json) and once you've
filled out committees.json with all 140 entries (start from
committees_template.json).
"""

import json

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"  # fast, 384-dim. Swap for "all-mpnet-base-v2" for higher quality.
TOP_K = 3  # keep each ticker's top-N committee matches
MIN_STRENGTH = 0.3  # drop matches below this normalized strength (0-1)



def load_json(path: str):
    with open(path) as f:
        return json.load(f)


def committee_label(c: dict) -> str:
    return f"{c['committee']} \u2013 {c['subcommittee']}" if c.get("subcommittee") else c["committee"]


def main():

    """
    {
                "ticker": ticker.upper(),
                "cik": cik,
                "name": profile["name"],
                "sic": profile["sic"],
                "sic_description": profile["sic_description"],
                # Default embedding text. This is the single biggest lever on
                # result quality — replace with a real 10-K "Item 1 Business"
                # excerpt or a yfinance longBusinessSummary if you have one,
                # since SIC description alone is a fairly coarse signal.
                "description": f"{profile['name']} operates in {profile['sic_description']}.",
            }
    """
    companies = load_json("companies.json")
    committees = load_json("committees.json")

    model = SentenceTransformer(MODEL_NAME)

    company_texts = [c["description"] for c in companies]
    committee_texts = [c["jurisdiction"] for c in committees]

    company_emb = model.encode(company_texts, normalize_embeddings=True)
    committee_emb = model.encode(committee_texts, normalize_embeddings=True)

    # Embeddings are L2-normalized, so cosine similarity is just a dot product.
    sim_matrix = company_emb @ committee_emb.T  # shape: (n_companies, n_committees)

    elements = []
    seen_committee_ids = set()

    for i, company in enumerate(companies):
        ticker = company["ticker"]
        elements.append({"data": {"id": ticker, "label": ticker, "type": "ticker"}})

        row = sim_matrix[i]
        # Min-max normalize this company's row so its strongest match is 1.0.
        # Raw cosine similarities for short text tend to cluster narrowly
        # (e.g. 0.3-0.6), which makes a poor edge-weight signal on its own.
        row_norm = (row - row.min()) / (row.max() - row.min() + 1e-9)

        top_indices = np.argsort(row)[::-1][:TOP_K]
        for j in top_indices:
            strength = float(row_norm[j])
            if strength < MIN_STRENGTH:
                continue

            committee = committees[j]
            committee_id = f"committee:{j}"

            if committee_id not in seen_committee_ids:
                elements.append(
                    {
                        "data": {
                            "id": committee_id,
                            "label": committee_label(committee),
                            "type": "committee",
                        }
                    }
                )
                seen_committee_ids.add(committee_id)

            elements.append(
                {
                    "data": {
                        "id": f"{ticker}->{committee_id}",
                        "source": ticker,
                        "target": committee_id,
                        "weight": round(strength, 3),
                    }
                }
            )

    with open("graph_elements.json", "w") as f:
        json.dump(elements, f, indent=2)

    print(f"wrote {len(elements)} elements to graph_elements.json")


if __name__ == "__main__":
    main()