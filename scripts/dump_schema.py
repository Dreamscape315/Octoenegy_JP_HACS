"""
Standard full GraphQL introspection query (including fields, arguments, return types, enums, etc.)
to fetch the live schema from Octopus Energy Japan and save it locally as JSON for offline analysis.
"""
import json
import urllib.request
import urllib.error

GRAPHQL_URL = "https://api.oejp-kraken.energy/v1/graphql/"

# Standard full introspection query (equivalent to graphql-js getIntrospectionQuery())
FULL_INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    subscriptionType { name }
    types {
      ...FullType
    }
    directives {
      name
      description
      locations
      args {
        ...InputValue
      }
    }
  }
}

fragment FullType on __Type {
  kind
  name
  description
  fields(includeDeprecated: true) {
    name
    description
    args {
      ...InputValue
    }
    type {
      ...TypeRef
    }
    isDeprecated
    deprecationReason
  }
  inputFields {
    ...InputValue
  }
  interfaces {
    ...TypeRef
  }
  enumValues(includeDeprecated: true) {
    name
    description
    isDeprecated
    deprecationReason
  }
  possibleTypes {
    ...TypeRef
  }
}

fragment InputValue on __InputValue {
  name
  description
  type { ...TypeRef }
  defaultValue
}

fragment TypeRef on __Type {
  kind
  name
  ofType {
    kind
    name
    ofType {
      kind
      name
      ofType {
        kind
        name
        ofType {
          kind
          name
          ofType {
            kind
            name
            ofType {
              kind
              name
              ofType {
                kind
                name
              }
            }
          }
        }
      }
    }
  }
}
"""


def main():
    payload = json.dumps({"query": FULL_INTROSPECTION_QUERY}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "application/json",
    }
    req = urllib.request.Request(GRAPHQL_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        status = e.code

    print(f"HTTP status: {status}, body length: {len(body)}")
    data = json.loads(body)
    if "errors" in data:
        print("errors:", json.dumps(data["errors"], ensure_ascii=False, indent=2)[:2000])

    out_path = "scripts/oejp_full_schema.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved to {out_path}")


if __name__ == "__main__":
    main()

