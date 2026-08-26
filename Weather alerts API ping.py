import datetime
import requests
import streamlit as st

st.set_page_config(page_title="Historical Heat Advisory Checker", page_icon="🚨", layout="centered")

st.title("🚨 Historical Heat Advisory Checker")
st.write("Query the National Weather Service archives (IEM API) for active heat events on a specific date.")

with st.form("search_form"):
    col1, col2 = st.columns(2)
    with col1:
        city = st.text_input("Enter City", value="Phoenix")
    with col2:
        state = st.text_input("Enter State (e.g., AZ)", value="AZ")
    
    target_date = st.date_input("Select Target Date", value=datetime.date(2026, 8, 4))
    submitted = st.form_submit_button("Search Historical Alerts")

if submitted:
    if not city or not state:
        st.error("Please enter both a city and a state.")
    else:
        # Nominatim OpenStreetMap Geocoding
        geo_url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "HeatAdvisoryChecker/1.0"}
        params = {"q": f"{city}, {state}, USA", "format": "json", "limit": 1}
        
        try:
            geo_response = requests.get(geo_url, headers=headers, params=params, timeout=10)
            geo_response.raise_for_status()
            geo_data = geo_response.json()
            
            if not geo_data:
                st.error("Location not found. Please verify the city and state.")
            else:
                lat = float(geo_data[0]["lat"])
                lon = float(geo_data[0]["lon"])
                display_name = geo_data[0]["display_name"]
                
                st.success(f"**Found Location:** {display_name}")
                st.info(f"**Coordinates:** Lat {lat:.7f}, Lon {lon:.7f}")
                st.markdown("---")
                st.subheader("--- RESULTS ---")
                
                # Format target timestamp to ISO 8601 UTC string for IEM SBW Point lookup
                valid_time = f"{target_date.strftime('%Y-%m-%d')}T18:00:00Z"
                
                # Correct IEM GeoJSON Point-in-Time Warning Endpoint
                iem_url = "https://mesonet.agron.iastate.edu/geojson/sbw-by-point.py"
                iem_params = {
                    "lat": lat,
                    "lon": lon,
                    "valid": valid_time
                }
                
                iem_response = requests.get(iem_url, params=iem_params, timeout=10)
                
                if iem_response.status_code == 200:
                    data = iem_response.json()
                    features = data.get("features", [])
                    
                    if not features:
                        st.warning("No active storm-based warnings or heat advisories found for this exact location and date/time.")
                    else:
                        for feature in features:
                            props = feature.get("properties", {})
                            event_name = props.get("phenomena_str", "Alert")
                            significance = props.get("significance_str", "")
                            wfo = props.get("wfo", "")
                            issue = props.get("issue", "")
                            expire = props.get("expire", "")
                            
                            st.error(f"**{event_name} - {significance}**")
                            st.write(f"**Issuing WFO:** {wfo}")
                            st.write(f"**Issued:** {issue}")
                            st.write(f"**Expires:** {expire}")
                else:
                    st.error(f"IEM API request failed (HTTP {iem_response.status_code})")
                    
        except requests.RequestException as e:
            st.error(f"Network error occurred: {e}")
