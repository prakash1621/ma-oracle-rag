def merge_results(results):
    combined = []

    for r in results:
        combined.extend(r)

    # sort by score
    combined = sorted(combined, key=lambda x: x.get("score", 0), reverse=True)

    return combined