def route_query(query):
    query = query.lower()

    if "revenue" in query or "balance sheet" in query:
        return "xbrl"

    elif "patent" in query or "invention" in query:
        return "patent"

    return "pinecone"