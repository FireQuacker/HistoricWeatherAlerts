import requests
import urllib.parse
from datetime import datetime
import pytz
from timezonefinder import TimezoneFinder
import streamlit as st

def geocode_location(city: str, state: str) -> dict:
    """Geocodes a City and State using the free Nominatim (OpenStreetMap) API."""
    # Append USA to ensure domestic results
    query = f"{city}, {state}, USA"
    encoded_query = urllib.parse.quote(query)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded_query}&format=json&limit=1"
    
    # Nominatim requires a user-agent
    headers = {"User-Agent": "OSHA-Historical-Heat-Checker/1.0"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data:
                return {
                    "latitude": float(data[0]["lat"]),
                    "longitude": float(data[0]["lon"]),
                    "display_name": data[0]["display_name"]
                }
        return {"error": "Location not found."}
    except Exception as e:
        return {"error": f"Geocoding error: {e}"}

def check_historical_heat_advisories(lat: float, lon: float, target_date_str: str) -> list:
    """
    Queries the IEM API for historical alerts at a specific coordinate and filters
    for heat events that were active on the target calendar date (local time).
    """
    # 1. Determine local timezone to accurately compare UTC alert times to the local calendar day
    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lng=lon, lat=lat)
    local_tz = pytz.timezone(tz_name) if tz_name else pytz.UTC
    
    # Parse the target date
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()

    # 2. Query the IEM Point-in-Polygon API
    # This endpoint returns ALL historical warnings for this exact lat/lon
    url = f"https://mesonet.agron.iastate.edu/api/1/ws.json?lat={lat}&lon={lon}"
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            return [{"error": f"IEM API request failed (HTTP {response.status_code})"}]
            
        alerts = response.json()
    except Exception as e:
        return [{"error": f"Failed to connect to IEM API: {e}"}]

    # 3. Filter the results
    # Heat-related VTEC phenomena codes: HT (Heat), EH (Excessive Heat)
    heat_codes = ["HT", "EH"]
    
    # VTEC significance codes dictionary for readability
    sig_map = {"W": "Warning", "Y": "Advisory", "A": "Watch", "S": "Statement"}
    
    active_heat_events = []
    
    for alert in alerts:
        phenom = alert.get("phenomena")
        
        # Only process heat-related events
        if phenom in heat_codes:
            # The IEM API returns ISO8601 strings in UTC (e.g., '2023-07-27T16:00:00Z')
            issue_utc = datetime.strptime(alert["issue"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
            expire_utc = datetime.strptime(alert["expire"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
            
            # Convert UTC times to the location's local time
            issue_local = issue_utc.astimezone(local_tz)
            expire_local = expire_utc.astimezone(local_tz)
            
            # Check if the alert was active at ANY point during the target calendar date
            # (i.e., it started on or before the target date AND ended on or after the target date)
            if issue_local.date() <= target_date <= expire_local.date():
                
                sig_code = alert.get("significance")
                event_type = "Excessive Heat" if phenom == "EH" else "Heat"
                event_severity = sig_map.get(sig_code, "Alert")
                
                active_heat_events.append({
                    "event_name": f"{event_type} {event_severity}",
                    "issued_local": issue_local.strftime("%Y-%m-%d %I:%M %p %Z"),
                    "expired_local": expire_local.strftime("%Y-%m-%d %I:%M %p %Z"),
                    "nws_office": alert.get("wfo"),
                    "event_id": alert.get("eventid")
                })
                
    return active_heat_events

# ==========================================
# STREAMLIT USER INTERFACE
# ==========================================
def main():
    st.set_page_config(page_title="Historical Heat Advisory Checker", page_icon="🚨", layout="centered")
    
    st.title("🚨 Historical Heat Advisory Checker")
    st.markdown("Query the **National Weather Service archives (IEM API)** for active heat events on a specific date.")
    
    # Create the search form using Streamlit inputs
    with st.form("heat_search_form"):
        col1, col2 = st.columns(2)
        with col1:
            city_input = st.text_input("Enter City", value="Phoenix")
        with col2:
            state_input = st.text_input("Enter State (e.g., AZ)", value="AZ")
        
        date_input = st.date_input("Select Target Date")
        submit_button = st.form_submit_button("Search Historical Alerts")
        
    if submit_button:
        if not city_input or not state_input:
            st.error("Please enter both a City and State.")
            return
            
        # Convert the Streamlit date object back to a string for the underlying function
        date_str = date_input.strftime("%Y-%m-%d")
        
        with st.spinner("Resolving coordinates..."):
            geo_data = geocode_location(city_input, state_input)
            
        if "error" in geo_data:
            st.error(f"Error: {geo_data['error']}")
            return
            
        lat = geo_data['latitude']
        lon = geo_data['longitude']
        
        st.success(f"**Found Location:** {geo_data['display_name']}")
        st.info(f"**Coordinates:** Lat {lat}, Lon {lon}")
        
        with st.spinner("Checking NWS archives (IEM API)..."):
            results = check_historical_heat_advisories(lat, lon, date_str)
            
        st.divider()
        st.subheader("--- RESULTS ---")
        
        if not results:
            st.info(f"No Heat Advisories or Excessive Heat Warnings found for this location on {date_str}.")
        elif "error" in results[0]:
            st.error(results[0]["error"])
        else:
            st.warning(f"Found {len(results)} active heat event(s) on {date_str}:")
            for event in results:
                with st.expander(f"🚨 {event['event_name']}", expanded=True):
                    st.write(f"**Issued By:** NWS {event['nws_office']}")
                    st.write(f"**Active From:** {event['issued_local']}")
                    st.write(f"**Active To:** {event['expired_local']}")
                    st.write(f"**Event ID:** {event['event_id']}")

if __name__ == "__main__":
    main()
