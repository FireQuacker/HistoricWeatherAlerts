import requests
import urllib.parse
from datetime import datetime
import pytz
from timezonefinder import TimezoneFinder
import streamlit as st

# ==========================================
# API UTILITIES WITH CACHING & ERROR HANDLING
# ==========================================

@st.cache_data(ttl=3600, show_spinner=False)
def geocode_location(city: str, state: str) -> dict:
    """
    Geocodes a City and State using the free Nominatim (OpenStreetMap) API.
    Cached for 1 hour to comply with OSM usage guidelines.
    """
    query = f"{city.strip()}, {state.strip()}, USA"
    encoded_query = urllib.parse.quote(query)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded_query}&format=json&limit=1"
    
    headers = {"User-Agent": "OSHA-Historical-Heat-Checker/1.0 (Streamlit App)"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, list) and len(data) > 0:
            return {
                "latitude": float(data[0]["lat"]),
                "longitude": float(data[0]["lon"]),
                "display_name": data[0]["display_name"]
            }
        return {"error": f"No location found for '{city}, {state}'."}
        
    except requests.exceptions.Timeout:
        return {"error": "Geocoding service timed out. Please try again."}
    except requests.exceptions.RequestException as e:
        return {"error": f"Geocoding network error: {e}"}
    except (ValueError, KeyError):
        return {"error": "Received an invalid response from the geocoding service."}


@st.cache_data(ttl=1800, show_spinner=False)
def check_historical_heat_advisories(lat: float, lon: float, target_date_str: str) -> list:
    """
    Queries the IEM API for historical alerts at a specific coordinate and filters
    for heat events active on the target calendar date (local time).
    """
    # 1. Determine local timezone
    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lng=lon, lat=lat)
    local_tz = pytz.timezone(tz_name) if tz_name else pytz.UTC
    
    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    except ValueError:
        return [{"error": f"Invalid date format: {target_date_str}. Expected YYYY-MM-DD."}]

    # 2. Query the IEM Point-in-Polygon API
    url = f"https://mesonet.agron.iastate.edu/api/1/ws.json?lat={lat}&lon={lon}"
    
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        raw_data = response.json()
    except requests.exceptions.Timeout:
        return [{"error": "IEM API request timed out. Please try again."}]
    except requests.exceptions.HTTPError as e:
        return [{"error": f"IEM API HTTP error (Status {response.status_code}): {e}"}]
    except requests.exceptions.RequestException as e:
        return [{"error": f"Failed to connect to IEM API: {e}"}]
    except ValueError:
        return [{"error": "Invalid JSON data returned by IEM API."}]

    # Normalize response format (handles top-level list or dictionary wrapper)
    if isinstance(raw_data, dict):
        alerts = raw_data.get("data", raw_data.get("events", []))
    elif isinstance(raw_data, list):
        alerts = raw_data
    else:
        alerts = []

    # 3. Filter Heat Alerts
    heat_codes = ["HT", "EH"]
    sig_map = {"W": "Warning", "Y": "Advisory", "A": "Watch", "S": "Statement"}
    active_heat_events = []
    
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
            
        phenom = alert.get("phenomena")
        if phenom in heat_codes:
            issue_str = alert.get("issue")
            expire_str = alert.get("expire")
            
            if not issue_str or not expire_str:
                continue
            
            try:
                # Robust ISO-8601 date parsing
                issue_utc = datetime.fromisoformat(issue_str.replace("Z", "+00:00"))
                expire_utc = datetime.fromisoformat(expire_str.replace("Z", "+00:00"))
            except ValueError:
                continue # Skip records with unparseable timestamps
            
            # Convert UTC times to local time zone
            issue_local = issue_utc.astimezone(local_tz)
            expire_local = expire_utc.astimezone(local_tz)
            
            # Check if alert spans the target date
            if issue_local.date() <= target_date <= expire_local.date():
                sig_code = alert.get("significance", "")
                event_type = "Excessive Heat" if phenom == "EH" else "Heat"
                event_severity = sig_map.get(sig_code, "Alert")
                
                active_heat_events.append({
                    "event_name": f"{event_type} {event_severity}",
                    "issued_local": issue_local.strftime("%Y-%m-%d %I:%M %p %Z"),
                    "expired_local": expire_local.strftime("%Y-%m-%d %I:%M %p %Z"),
                    "nws_office": alert.get("wfo", "Unknown"),
                    "event_id": alert.get("eventid", "N/A")
                })
                
    return active_heat_events

# ==========================================
# STREAMLIT USER INTERFACE
# ==========================================
def main():
    st.set_page_config(page_title="Historical Heat Advisory Checker", page_icon="🚨", layout="centered")
    
    st.title("🚨 Historical Heat Advisory Checker")
    st.markdown("Query NWS archives via the **Iowa Environmental Mesonet (IEM) API** for active heat events on a specific date.")
    
    with st.form("heat_search_form"):
        col1, col2 = st.columns(2)
        with col1:
            city_input = st.text_input("Enter City", value="Phoenix")
        with col2:
            state_input = st.text_input("Enter State (e.g., AZ)", value="AZ")
        
        date_input = st.date_input("Select Target Date")
        submit_button = st.form_submit_button("Search Historical Alerts")
        
    if submit_button:
        if not city_input.strip() or not state_input.strip():
            st.error("Please enter both a City and State.")
            return
            
        date_str = date_input.strftime("%Y-%m-%d")
        
        with st.spinner("Resolving coordinates..."):
            geo_data = geocode_location(city_input, state_input)
            
        if "error" in geo_data:
            st.error(f"Geocoding Error: {geo_data['error']}")
            return
            
        lat = geo_data['latitude']
        lon = geo_data['longitude']
        
        st.success(f"**Location Resolved:** {geo_data['display_name']}")
        st.caption(f"Coordinates: Latitude `{lat}`, Longitude `{lon}`")
        
        with st.spinner("Fetching historical NWS alerts from IEM archives..."):
            results = check_historical_heat_advisories(lat, lon, date_str)
            
        st.divider()
        
        if len(results) > 0 and "error" in results[0]:
            st.error(f"API Error: {results[0]['error']}")
        elif not results:
            st.info(f"No Heat Advisories or Excessive Heat Warnings were active for this location on **{date_str}**.")
        else:
            st.warning(f"Found **{len(results)}** active heat event(s) on **{date_str}**:")
            for event in results:
                with st.expander(f"🚨 {event['event_name']}", expanded=True):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.write(f"**Issued By:** NWS `{event['nws_office']}`")
                        st.write(f"**Event ID:** `{event['event_id']}`")
                    with col_b:
                        st.write(f"**Active From:** {event['issued_local']}")
                        st.write(f"**Active To:** {event['expired_local']}")

if __name__ == "__main__":
    main()
