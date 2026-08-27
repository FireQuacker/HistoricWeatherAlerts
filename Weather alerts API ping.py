import streamlit as st
import requests
import pandas as pd
from datetime import datetime, time, timezone

# -----------------------------------------------------------------------------
# Configuration & Setup
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="OSHA Historic NWS Heat Alert Lookup",
    page_icon="🤓",
    layout="wide"
)

# Custom User-Agent for Nominatim and IEM compliance
USER_AGENT = "OSHA_HeatAlert_Lookup/1.0 (contact: andreodu@gmail.com)"
HEADERS = {"User-Agent": USER_AGENT}

# State name to abbreviation mapping for user convenience
STATE_MAP = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR', 'california': 'CA',
    'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE', 'florida': 'FL', 'georgia': 'GA',
    'hawaii': 'HI', 'idaho': 'ID', 'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA',
    'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
    'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN', 'mississippi': 'MS', 'missouri': 'MO',
    'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV', 'new hampshire': 'NH', 'new jersey': 'NJ',
    'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH',
    'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC',
    'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT', 'vermont': 'VT',
    'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY'
}

def get_state_code(state_input: str) -> str:
    cleaned = state_input.strip().lower()
    if len(cleaned) == 2:
        return cleaned.upper()
    return STATE_MAP.get(cleaned, cleaned.upper())

# -----------------------------------------------------------------------------
# Helper Functions with Caching & Rate-Limit Resilience
# -----------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def geocode_location(city: str, state_abbr: str):
    """
    Geocodes city and state using Nominatim. Handles HTTP 429 gracefully 
    so the app never crashes due to rate limits.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "city": city.strip(),
        "state": state_abbr,
        "country": "United States",
        "format": "json",
        "addressdetails": 1,
        "limit": 1
    }
    
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=8)
        
        if response.status_code == 429:
            return {
                "lat": 38.0, "lon": -78.0, 
                "name": f"{city.title()}, {state_abbr} (Rate-limited, using regional lookup)", 
                "county": ""
            }, "WARNING_429"
            
        response.raise_for_status()
        data = response.json()
        
        if not data:
            return None, "Location not found. Please verify city and state spelling."
        
        item = data[0]
        lat = float(item["lat"])
        lon = float(item["lon"])
        display_name = item.get("display_name", f"{city}, {state_abbr}")
        address = item.get("address", {})
        county = address.get("county", "")
        
        return {"lat": lat, "lon": lon, "name": display_name, "county": county}, None

    except requests.exceptions.RequestException as e:
        return {
            "lat": 38.0, "lon": -78.0, 
            "name": f"{city.title()}, {state_abbr} (Offline Fallback)", 
            "county": ""
        }, f"Geocoding notice: {str(e)}"

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_iem_state_heat_events(state_abbr: str, year: int):
    """
    Fetches all VTEC events for a state and year from IEM.
    """
    url = "https://mesonet.agron.iastate.edu/json/vtec_events_bystate.py"
    params = {
        "state": state_abbr,
        "year": year
    }

    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=25)
        
        if response.status_code == 200:
            try:
                data = response.json()
                return data.get("vtec_events", []), None
            except ValueError:
                return None, f"Failed to parse IEM JSON response. Raw text: {response.text[:200]}"
        else:
            return None, f"IEM API error status {response.status_code}"
            
    except requests.exceptions.RequestException as e:
        return None, f"Network request failed: {str(e)}"

def filter_active_heat_alerts(events: list, target_date: datetime.date):
    """
    Filters events active on the target date specifically for heat phenomena 
    including HT (Heat), EH (Excessive Heat), and XH (Extreme Heat).
    """
    active_alerts = []
    
    target_start = datetime.combine(target_date, time.min).replace(tzinfo=timezone.utc)
    target_end = datetime.combine(target_date, time.max).replace(tzinfo=timezone.utc)

    for event in events:
        phenomena = event.get("phenomena", "")
        
        # Expanded to include modern 'XH' (Extreme Heat) alongside 'HT' and 'EH'
        if phenomena not in ["HT", "EH", "XH"]:
            continue

        issue_str = event.get("issue")
        expire_str = event.get("expire")
        
        if not issue_str or not expire_str:
            continue

        try:
            issue_dt = datetime.fromisoformat(issue_str.replace("Z", "+00:00"))
            expire_dt = datetime.fromisoformat(expire_str.replace("Z", "+00:00"))

            # Interval overlap check for multi-day alerts
            if issue_dt <= target_end and expire_dt >= target_start:
                significance = event.get("significance", "")
                
                phen_map = {
                    "HT": "Heat", 
                    "EH": "Excessive Heat", 
                    "XH": "Extreme Heat"
                }
                sig_map = {"W": "Warning", "A": "Watch", "Y": "Advisory"}
                
                p_name = phen_map.get(phenomena, phenomena)
                s_name = sig_map.get(significance, significance)
                area_desc = event.get("area_name", "Unknown Area")
                
                active_alerts.append({
                    "Alert Type": f"{p_name} {s_name}",
                    "Issuing WFO": event.get("wfo"),
                    "Area / County": area_desc,
                    "Issued (UTC)": issue_dt.strftime("%Y-%m-%d %H:%M"),
                    "Expires (UTC)": expire_dt.strftime("%Y-%m-%d %H:%M"),
                    "Event ID": event.get("eventid"),
                    "NWS Text Record URL": event.get("url")
                })
        except ValueError:
            continue

    return pd.DataFrame(active_alerts)

# -----------------------------------------------------------------------------
# Streamlit UI Layout
# -----------------------------------------------------------------------------
st.title("🛡️ OSHA Historic NWS Heat Alert Lookup")
st.markdown(
    "**Compliance Investigation Tool:** Quickly verify official National Weather Service "
    "(NWS) heat advisories and warnings for any location and date to establish employer knowledge."
)

st.divider()

# Sidebar Inputs
with st.sidebar:
    st.header("Investigation Parameters")
    st.markdown("Enter the jobsite location and inspection date:")
    
    city_input = st.text_input("City", value="Chesapeake", placeholder="e.g., Manassas, Houston")
    state_input = st.text_input("State (Name or Abbr)", value="Virginia", placeholder="e.g., Virginia, TX")
    target_date = st.date_input("Incident / Inspection Date", value=datetime(2026, 7, 3))
    
    query_btn = st.button("Check Historic Alerts", type="primary", use_container_width=True)

# Main Application Logic
if query_btn:
    if not city_input or not state_input:
        st.warning("⚠️ Please provide both a city and a state.")
    else:
        state_abbr = get_state_code(state_input)
        
        with st.spinner("Resolving location coordinates..."):
            loc_data, geo_err = geocode_location(city_input, state_abbr)

        if geo_err == "WARNING_429":
            st.warning("⚠️ OpenStreetMap rate limit reached (HTTP 429). Proceeding directly with state-wide IEM archive check.")
        elif geo_err and loc_data is None:
            st.error(f"❌ {geo_err}")
            st.stop()

        if loc_data:
            lat = loc_data["lat"]
            lon = loc_data["lon"]
            county = loc_data["county"]
            
            # Display Investigator Summary
            col1, col2 = st.columns([2, 1])
            with col1:
                st.subheader("📍 Jobsite Verification")
                st.write(f"**Resolved Location:** {loc_data['name']}")
                if county:
                    st.write(f"**Identified County/District:** {county}")
                st.write(f"**Coordinates:** {lat:.4f}° N, {lon:.4f}° W")
                st.write(f"**Target Inquiry Date:** {target_date.strftime('%B %d, %Y')}")
            
            with col2:
                map_df = pd.DataFrame({"lat": [lat], "lon": [lon]})
                st.map(map_df, zoom=9, use_container_width=True)

            st.divider()

            # Fetch IEM State Alerts for the Year
            year = target_date.year
            with st.spinner(f"Querying IEM historical archive for {state_abbr} ({year})..."):
                raw_events, iem_err = fetch_iem_state_heat_events(state_abbr, year)

            if iem_err:
                st.error(f"❌ {iem_err}")
            elif not raw_events:
                st.info(f"ℹ️ No weather alert records found in IEM for {state_abbr} in {year}.")
            else:
                # Filter for active heat alerts on target date
                df_active = filter_active_heat_alerts(raw_events, target_date)

                st.subheader("📋 NWS Heat Advisory & Warning Audit Results")

                if df_active.empty:
                    st.success(
                        f"✅ **No official NWS Heat Advisories or Warnings** were active in {state_abbr} "
                        f"on {target_date.strftime('%Y-%m-%d')}."
                    )
                else:
                    st.warning(
                        f"⚠️ **Evidentiary Match Found:** {len(df_active)} heat-related alert(s) were active "
                        f"on this date in the region."
                    )
                    
                    # Display table
                    table_cols = ["Alert Type", "Area / County", "Issued (UTC)", "Expires (UTC)", "Event ID"]
                    st.dataframe(df_active[table_cols], use_container_width=True)

                    # Detailed evidentiary breakdown for case file
                    st.markdown("### 📄 Detailed Alert Records for Case File")
                    for _, row in df_active.iterrows():
                        with st.expander(f"📌 {row['Alert Type']} — {row['Area / County']} (Event ID: {row['Event ID']})"):
                            st.write(f"**Issuing WFO:** {row['Issuing WFO']}")
                            st.write(f"**Effective Start (UTC):** {row['Issued (UTC)']}")
                            st.write(f"**Effective Expiration (UTC):** {row['Expires (UTC)']}")
                            if row.get("NWS Text Record URL"):
                                st.markdown(f"[🔗 View Official NWS/IEM Text Record]({row['NWS Text Record URL']})")
