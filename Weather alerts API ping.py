import streamlit as st
import requests
import pandas as pd
from datetime import datetime, time, timezone

# -----------------------------------------------------------------------------
# Configuration & Setup
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="NWS Historical Heat Alert Tracker",
    page_icon="☀️",
    layout="wide"
)

# Custom User-Agent to satisfy API requirements and prevent HTTP 403/404 blocks
USER_AGENT = "StreamlitHeatAlertApp/1.0 (contact: andreodu@gmail.com)"
HEADERS = {"User-Agent": USER_AGENT}

HEAT_PHENOMENA = {
    "HT": "Heat",
    "EH": "Excessive Heat"
}

SIGNIFICANCE_CODES = {
    "W": "Warning",
    "A": "Watch",
    "Y": "Advisory",
    "S": "Statement"
}

# -----------------------------------------------------------------------------
# Helper Functions with Caching and Error Handling
# -----------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def geocode_location(city: str, state: str):
    """
    Converts City and State into Latitude and Longitude using Nominatim.
    Includes error handling for network issues and missing locations.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "city": city.strip(),
        "state": state.strip(),
        "country": "United States",
        "format": "json",
        "limit": 1
    }
    
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not data:
            return None, "Location not found. Please verify city and state spelling."
        
        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        display_name = data[0].get("display_name", f"{city}, {state}")
        return {"lat": lat, "lon": lon, "name": display_name}, None

    except requests.exceptions.RequestException as e:
        return None, f"Geocoding service error: {str(e)}"


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_iem_alerts(lat: float, lon: float):
    """
    Queries historical VTEC events for a lat/lon coordinate from IEM.
    Includes strict JSON parsing and status code validation.
    """
    url = "https://mesonet.agron.iastate.edu/json/vtec_events_by_latlon.py"
    params = {
        "lat": lat,
        "lon": lon
    }

    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=15)
        
        # Validate the response status code before attempting to parse JSON
        if response.status_code == 200:
            try:
                data = response.json()
                events = data.get("events", [])
                return events, None
            except ValueError:
                # Catches the "Expecting value" error when IEM returns an HTML error page
                return None, f"Failed to parse JSON. Raw response from IEM: {response.text[:200]}"
        else:
            return None, f"IEM API failed with status {response.status_code}. Details: {response.text[:200]}"

    except requests.exceptions.RequestException as e:
        return None, f"Failed to fetch historical alerts from IEM: {str(e)}"


def filter_heat_alerts(events: list, target_date: datetime.date):
    """
    Filters VTEC event records for heat-related alerts active on the target date.
    """
    heat_events = []
    
    # Define start and end of the target day in UTC
    target_start = datetime.combine(target_date, time.min).replace(tzinfo=timezone.utc)
    target_end = datetime.combine(target_date, time.max).replace(tzinfo=timezone.utc)

    for event in events:
        phenomena = event.get("phenomena", "")
        
        # Check if the alert is heat-related (HT or EH)
        if phenomena in HEAT_PHENOMENA:
            try:
                # IEM VTEC ISO Timestamps
                issue_str = event.get("issue")
                expire_str = event.get("expire")
                
                if not issue_str or not expire_str:
                    continue

                issue_dt = datetime.fromisoformat(issue_str.replace("Z", "+00:00"))
                expire_dt = datetime.fromisoformat(expire_str.replace("Z", "+00:00"))

                # Alert was active if it overlaps with target day
                if issue_dt <= target_end and expire_dt >= target_start:
                    sig_code = event.get("significance", "")
                    sig_name = SIGNIFICANCE_CODES.get(sig_code, sig_code)
                    phen_name = HEAT_PHENOMENA.get(phenomena, phenomena)
                    
                    heat_events.append({
                        "Event Type": f"{phen_name} {sig_name}",
                        "WFO": event.get("wfo"),
                        "Issued (UTC)": issue_dt.strftime("%Y-%m-%d %H:%M"),
                        "Expired (UTC)": expire_dt.strftime("%Y-%m-%d %H:%M"),
                        "Event ID": event.get("eventid"),
                        "Phenomena": phenomena,
                        "Significance": sig_code,
                        "HVTEC NWS Text URL": event.get("url")
                    })
            except ValueError:
                continue

    return pd.DataFrame(heat_events)


# -----------------------------------------------------------------------------
# Streamlit UI Layout
# -----------------------------------------------------------------------------
st.title("☀️ NWS Historical Heat Alert Tracker")
st.markdown(
    "Query historical **National Weather Service (NWS)** Heat Advisories, Watches, "
    "and Warnings powered by the **Iowa Environmental Mesonet (IEM)** archive."
)

st.divider()

# Sidebar Inputs
with st.sidebar:
    st.header("Search Parameters")
    city_input = st.text_input("City", value="Phoenix")
    state_input = st.text_input("State (or abbreviation)", value="Arizona")
    selected_date = st.date_input("Target Date", value=datetime(2023, 7, 15))
    
    search_button = st.button("Query Alerts", type="primary", use_container_width=True)

# Application Logic
if search_button:
    if not city_input or not state_input:
        st.warning("Please provide both a city and a state.")
    else:
        with st.spinner("Geocoding location..."):
            location_data, geo_error = geocode_location(city_input, state_input)

        if geo_error:
            st.error(f"❌ {geo_error}")
        else:
            lat = location_data["lat"]
            lon = location_data["lon"]
            
            # Display Location Summary
            col1, col2 = st.columns([2, 1])
            with col1:
                st.subheader("Location Metadata")
                st.write(f"**Found Location:** {location_data['name']}")
                st.write(f"**Coordinates:** {lat:.4f}° N, {lon:.4f}° W")
                st.write(f"**Query Date:** {selected_date.strftime('%B %d, %Y')}")
            
            with col2:
                # Interactive Map showing the point location
                map_df = pd.DataFrame({"lat": [lat], "lon": [lon]})
                st.map(map_df, zoom=9)

            st.divider()

            # Query IEM Alerts
            with st.spinner("Fetching historical alert archive from IEM..."):
                raw_events, iem_error = fetch_iem_alerts(lat, lon)

            if iem_error:
                st.error(f"❌ {iem_error}")
            elif not raw_events:
                st.info("ℹ️ No historical weather alert data found for these coordinates.")
            else:
                # Filter for heat alerts on the specified date
                df_heat = filter_heat_alerts(raw_events, selected_date)

                st.subheader(f"Heat Alerts Active on {selected_date.strftime('%Y-%m-%d')}")

                if df_heat.empty:
                    st.success("✅ No NWS Heat Advisories, Watches, or Warnings were active on this date for the selected location.")
                else:
                    st.warning(f"⚠️ Found {len(df_heat)} heat-related alert(s) on this date.")
                    
                    # Display Table
                    display_cols = ["Event Type", "WFO", "Issued (UTC)", "Expired (UTC)", "Event ID"]
                    st.dataframe(df_heat[display_cols], use_container_width=True)

                    # Display Detailed Cards
                    st.markdown("### Alert Breakdown")
                    for _, row in df_heat.iterrows():
                        with st.expander(f"📌 {row['Event Type']} (Event ID: {row['Event ID']})"):
                            st.write(f"**Issuing Weather Forecast Office (WFO):** {row['WFO']}")
                            st.write(f"**Issue Time:** {row['Issued (UTC)']} UTC")
                            st.write(f"**Expiration Time:** {row['Expired (UTC)']} UTC")
                            if row.get("HVTEC NWS Text URL"):
                                st.markdown(f"[View IEM Text Record]({row['HVTEC NWS Text URL']})")
