"""
Geocoding for Indian farm locations (shared by the /api/geocode endpoint, farm
saving, and the crop-recommendation model).

Strategy: curated agricultural hubs first (instant), then OpenStreetMap
Nominatim restricted to India, then a safe district/state-level fallback.
Results are cached in-process.
"""
import requests

_GEOCODE_CACHE = {}

INDIAN_AGRI_CITIES = [
    {"city": "Surat", "district": "Surat", "state": "Gujarat", "lat": 21.1702, "lon": 72.8311},
    {"city": "Ahmedabad", "district": "Ahmedabad", "state": "Gujarat", "lat": 23.0225, "lon": 72.5714},
    {"city": "Rajkot", "district": "Rajkot", "state": "Gujarat", "lat": 22.3039, "lon": 70.8022},
    {"city": "Vadodara", "district": "Vadodara", "state": "Gujarat", "lat": 22.3072, "lon": 73.1812},
    {"city": "Bhavnagar", "district": "Bhavnagar", "state": "Gujarat", "lat": 21.7645, "lon": 72.1519},
    {"city": "Junagadh", "district": "Junagadh", "state": "Gujarat", "lat": 21.5222, "lon": 70.4579},
    {"city": "Jamnagar", "district": "Jamnagar", "state": "Gujarat", "lat": 22.4707, "lon": 70.0577},
    {"city": "Anand", "district": "Anand", "state": "Gujarat", "lat": 22.5645, "lon": 72.9289},
    {"city": "Mehsana", "district": "Mehsana", "state": "Gujarat", "lat": 23.5880, "lon": 72.3693},
    {"city": "Pune", "district": "Pune", "state": "Maharashtra", "lat": 18.5204, "lon": 73.8567},
    {"city": "Nashik", "district": "Nashik", "state": "Maharashtra", "lat": 19.9975, "lon": 73.7898},
    {"city": "Nagpur", "district": "Nagpur", "state": "Maharashtra", "lat": 21.1458, "lon": 79.0882},
    {"city": "Kolhapur", "district": "Kolhapur", "state": "Maharashtra", "lat": 16.7050, "lon": 74.2433},
    {"city": "Solapur", "district": "Solapur", "state": "Maharashtra", "lat": 17.6599, "lon": 75.9064},
    {"city": "Aurangabad", "district": "Chhatrapati Sambhajinagar", "state": "Maharashtra", "lat": 19.8762, "lon": 75.3433},
    {"city": "Amravati", "district": "Amravati", "state": "Maharashtra", "lat": 20.9374, "lon": 77.7796},
    {"city": "Jalgaon", "district": "Jalgaon", "state": "Maharashtra", "lat": 21.0077, "lon": 75.5626},
    {"city": "Indore", "district": "Indore", "state": "Madhya Pradesh", "lat": 22.7196, "lon": 75.8577},
    {"city": "Bhopal", "district": "Bhopal", "state": "Madhya Pradesh", "lat": 23.2599, "lon": 77.4126},
    {"city": "Ujjain", "district": "Ujjain", "state": "Madhya Pradesh", "lat": 23.1765, "lon": 75.7885},
    {"city": "Jabalpur", "district": "Jabalpur", "state": "Madhya Pradesh", "lat": 23.1815, "lon": 79.9864},
    {"city": "Gwalior", "district": "Gwalior", "state": "Madhya Pradesh", "lat": 26.2183, "lon": 78.1828},
    {"city": "Jaipur", "district": "Jaipur", "state": "Rajasthan", "lat": 26.9124, "lon": 75.7873},
    {"city": "Jodhpur", "district": "Jodhpur", "state": "Rajasthan", "lat": 26.2389, "lon": 73.0243},
    {"city": "Kota", "district": "Kota", "state": "Rajasthan", "lat": 25.2138, "lon": 75.8648},
    {"city": "Bikaner", "district": "Bikaner", "state": "Rajasthan", "lat": 28.0229, "lon": 73.3119},
    {"city": "Sriganganagar", "district": "Ganganagar", "state": "Rajasthan", "lat": 29.9038, "lon": 73.8772},
    {"city": "Ludhiana", "district": "Ludhiana", "state": "Punjab", "lat": 30.9010, "lon": 75.8573},
    {"city": "Amritsar", "district": "Amritsar", "state": "Punjab", "lat": 31.6340, "lon": 74.8723},
    {"city": "Jalandhar", "district": "Jalandhar", "state": "Punjab", "lat": 31.3260, "lon": 75.5762},
    {"city": "Bathinda", "district": "Bathinda", "state": "Punjab", "lat": 30.2110, "lon": 74.9455},
    {"city": "Patiala", "district": "Patiala", "state": "Punjab", "lat": 30.3398, "lon": 76.3869},
    {"city": "Karnal", "district": "Karnal", "state": "Haryana", "lat": 29.6857, "lon": 76.9905},
    {"city": "Hisar", "district": "Hisar", "state": "Haryana", "lat": 29.1492, "lon": 75.7217},
    {"city": "Rohtak", "district": "Rohtak", "state": "Haryana", "lat": 28.8955, "lon": 76.6066},
    {"city": "Sirsa", "district": "Sirsa", "state": "Haryana", "lat": 29.5349, "lon": 75.0298},
    {"city": "Lucknow", "district": "Lucknow", "state": "Uttar Pradesh", "lat": 26.8467, "lon": 80.9462},
    {"city": "Varanasi", "district": "Varanasi", "state": "Uttar Pradesh", "lat": 25.3176, "lon": 82.9739},
    {"city": "Kanpur", "district": "Kanpur Nagar", "state": "Uttar Pradesh", "lat": 26.4499, "lon": 80.3319},
    {"city": "Agra", "district": "Agra", "state": "Uttar Pradesh", "lat": 27.1767, "lon": 78.0081},
    {"city": "Prayagraj", "district": "Prayagraj", "state": "Uttar Pradesh", "lat": 25.4358, "lon": 81.8463},
    {"city": "Gorakhpur", "district": "Gorakhpur", "state": "Uttar Pradesh", "lat": 26.7606, "lon": 83.3732},
    {"city": "Patna", "district": "Patna", "state": "Bihar", "lat": 25.5941, "lon": 85.1376},
    {"city": "Gaya", "district": "Gaya", "state": "Bihar", "lat": 24.7914, "lon": 85.0002},
    {"city": "Muzaffarpur", "district": "Muzaffarpur", "state": "Bihar", "lat": 26.1209, "lon": 85.3647},
    {"city": "Raipur", "district": "Raipur", "state": "Chhattisgarh", "lat": 21.2514, "lon": 81.6296},
    {"city": "Ranchi", "district": "Ranchi", "state": "Jharkhand", "lat": 23.3441, "lon": 85.3096},
    {"city": "Bhubaneswar", "district": "Khurda", "state": "Odisha", "lat": 20.2961, "lon": 85.8245},
    {"city": "Sambalpur", "district": "Sambalpur", "state": "Odisha", "lat": 21.4669, "lon": 83.9812},
    {"city": "Hyderabad", "district": "Hyderabad", "state": "Telangana", "lat": 17.3850, "lon": 78.4867},
    {"city": "Warangal", "district": "Warangal", "state": "Telangana", "lat": 17.9689, "lon": 79.5941},
    {"city": "Bengaluru", "district": "Bengaluru Urban", "state": "Karnataka", "lat": 12.9716, "lon": 77.5946},
    {"city": "Mysuru", "district": "Mysuru", "state": "Karnataka", "lat": 12.2958, "lon": 76.6394},
    {"city": "Hubballi", "district": "Dharwad", "state": "Karnataka", "lat": 15.3647, "lon": 75.1240},
    {"city": "Belagavi", "district": "Belagavi", "state": "Karnataka", "lat": 15.8497, "lon": 74.4977},
    {"city": "Vijayawada", "district": "NTR", "state": "Andhra Pradesh", "lat": 16.5062, "lon": 80.6480},
    {"city": "Visakhapatnam", "district": "Visakhapatnam", "state": "Andhra Pradesh", "lat": 17.6868, "lon": 83.2185},
    {"city": "Guntur", "district": "Guntur", "state": "Andhra Pradesh", "lat": 16.3067, "lon": 80.4365},
    {"city": "Chennai", "district": "Chennai", "state": "Tamil Nadu", "lat": 13.0827, "lon": 80.2707},
    {"city": "Coimbatore", "district": "Coimbatore", "state": "Tamil Nadu", "lat": 11.0168, "lon": 76.9558},
    {"city": "Madurai", "district": "Madurai", "state": "Tamil Nadu", "lat": 9.9252, "lon": 78.1198},
    {"city": "Salem", "district": "Salem", "state": "Tamil Nadu", "lat": 11.6643, "lon": 78.1460},
    {"city": "Kochi", "district": "Ernakulam", "state": "Kerala", "lat": 9.9312, "lon": 76.2673},
    {"city": "Thiruvananthapuram", "district": "Thiruvananthapuram", "state": "Kerala", "lat": 8.5241, "lon": 76.9366},
    {"city": "Kolkata", "district": "Kolkata", "state": "West Bengal", "lat": 22.5726, "lon": 88.3639},
    {"city": "Siliguri", "district": "Darjeeling", "state": "West Bengal", "lat": 26.7271, "lon": 88.3953},
]


def geocode_lookup(q, limit=5):
    """Resolve a free-text Indian location.

    Returns the same dict the /api/geocode endpoint returns
    ({query, address, display_name, city, district, state, lat, lon,
    is_approximate, match_level, original_query, results}), or None when
    nothing matches.
    """
    q = (q or "").strip()
    if not q:
        return None
    limit = max(1, min(10, int(limit)))

    cache_key = f"{q.lower()}:{limit}"
    if cache_key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[cache_key]

    q_lower = q.lower()
    combined_candidates = []
    seen_keys = set()

    # 1. Match local curated agricultural hubs (instant, deduplicated, zero-latency)
    for c in INDIAN_AGRI_CITIES:
        c_name = c["city"].lower()
        if c_name.startswith(q_lower) or q_lower in c_name:
            k = f"{c['city'].lower()}:{c['state'].lower()}"
            if k not in seen_keys:
                seen_keys.add(k)
                has_distinct_district = c.get('district') and c['district'].lower() != c['city'].lower()
                clean_addr = f"{c['city']}, {c['district']}, {c['state']}, India" if has_distinct_district else f"{c['city']}, {c['state']}, India"
                combined_candidates.append({
                    'query': q,
                    'address': clean_addr,
                    'display_name': clean_addr,
                    'city': c['city'],
                    'district': c.get('district', ''),
                    'state': c['state'],
                    'lat': c['lat'],
                    'lon': c['lon'],
                    'place_id': f"local_{c['city'].lower()}",
                    '_score': 0 if c_name == q_lower else 1 if c_name.startswith(q_lower) else 2
                })

    # 2. Query Nominatim restricted to India (&countrycodes=in)
    headers = {
        'User-Agent': 'KrishiMitra-App/1.0 (agronomy-dev@krishimitra.org)',
        'Accept': 'application/json'
    }
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={requests.utils.quote(q)}&addressdetails=1&countrycodes=in&limit=8"
    
    try:
        resp = requests.get(url, headers=headers, timeout=(3.0, 8.0))
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    addr = item.get('address', {})
                    city = addr.get('city') or addr.get('town') or addr.get('village') or addr.get('suburb') or addr.get('county') or ''
                    state = addr.get('state') or ''
                    district = addr.get('state_district') or addr.get('county') or ''
                    disp = item.get('display_name') or q

                    if not city:
                        city = disp.split(',')[0].strip()

                    try:
                        lat = float(item.get('lat'))
                        lon = float(item.get('lon'))
                    except (TypeError, ValueError):
                        continue

                    k = f"{city.lower()}:{state.lower()}"
                    if k in seen_keys:
                        continue
                    seen_keys.add(k)

                    parts = [city, district, state, "India"]
                    clean_parts = []
                    for p in parts:
                        if p and p not in clean_parts:
                            clean_parts.append(p)
                    clean_addr = ', '.join(clean_parts)

                    c_lower = city.lower()
                    score = 0 if c_lower == q_lower else 1 if c_lower.startswith(q_lower) else 2

                    combined_candidates.append({
                        'query': q,
                        'address': clean_addr,
                        'display_name': clean_addr,
                        'city': city,
                        'district': district,
                        'state': state,
                        'lat': lat,
                        'lon': lon,
                        'place_id': item.get('place_id'),
                        'raw_address': addr,
                        '_score': score
                    })
    except Exception:
        # Nominatim may be slow or offline; local curated hub matches provide robust fallback
        pass

    # Sort candidates: exact prefix matches first, then shortest names
    combined_candidates.sort(key=lambda x: (x.get('_score', 3), len(x.get('city', ''))))

    # Strip internal score before returning
    for c in combined_candidates:
        c.pop('_score', None)

    results = combined_candidates[:limit]

    # 3. Safe Hierarchical Geocoding (approximate regional/district fallback)
    # If no exact city match was found, inspect comma-separated or tokenized sub-parts
    # (e.g. "Navrangpura, Gujarat" -> tokens: "Navrangpura", "Gujarat").
    # Never substitute an unrelated location; only match if a valid district or state is explicitly present.
    if not results:
        raw_tokens = [t.strip().lower() for t in q.split(',') if t.strip()]
        hierarchical_match = None
        match_level = None

        # 3a. Check if any individual token matches a known city or district
        for tok in raw_tokens:
            for c in INDIAN_AGRI_CITIES:
                if c["city"].lower() == tok or (c.get("district") and c["district"].lower() == tok):
                    hierarchical_match = c
                    match_level = "district_hub"
                    break
            if hierarchical_match:
                break

        # 3b. If still no match, check if any token matches an Indian state
        if not hierarchical_match:
            primary_state_hubs = {
                "gujarat": "ahmedabad", "maharashtra": "pune", "punjab": "ludhiana",
                "rajasthan": "jaipur", "karnataka": "bengaluru", "tamil nadu": "chennai",
                "uttar pradesh": "lucknow", "madhya pradesh": "bhopal", "haryana": "karnal",
                "west bengal": "kolkata", "bihar": "patna", "telangana": "hyderabad",
                "andhra pradesh": "vijayawada", "odisha": "bhubaneswar", "kerala": "kochi",
                "chhattisgarh": "raipur", "jharkhand": "ranchi"
            }
            for tok in raw_tokens:
                preferred_city = primary_state_hubs.get(tok)
                if preferred_city:
                    for c in INDIAN_AGRI_CITIES:
                        if c["city"].lower() == preferred_city:
                            hierarchical_match = c
                            match_level = "regional_hub"
                            break
                if hierarchical_match:
                    break
                # Fallback to any city matching the state
                for c in INDIAN_AGRI_CITIES:
                    if c["state"].lower() == tok:
                        hierarchical_match = c
                        match_level = "regional_hub"
                        break
                if hierarchical_match:
                    break

        if hierarchical_match:
            c = hierarchical_match
            disp = f"{c['city']}, {c['state']} (Regional Center for {q})"
            addr = f"{c['city']}, {c['district']}, {c['state']}, India" if c.get('district') else f"{c['city']}, {c['state']}, India"
            approx_item = {
                'query': q,
                'address': addr,
                'display_name': disp,
                'city': c['city'],
                'district': c.get('district', ''),
                'state': c['state'],
                'lat': c['lat'],
                'lon': c['lon'],
                'place_id': f"regional_{c['city'].lower()}",
                'is_approximate': True,
                'match_level': match_level,
                'original_query': q,
            }
            results = [approx_item]

    if not results:
        return None

    first = results[0]
    out = {
        'query': q,
        'address': first['address'],
        'display_name': first['display_name'],
        'city': first['city'],
        'district': first['district'],
        'state': first['state'],
        'lat': first['lat'],
        'lon': first['lon'],
        'is_approximate': first.get('is_approximate', False),
        'match_level': first.get('match_level', 'exact'),
        'original_query': first.get('original_query', q),
        'results': results
    }
    _GEOCODE_CACHE[cache_key] = out
    return out
