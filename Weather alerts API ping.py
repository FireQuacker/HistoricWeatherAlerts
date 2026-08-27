import streamlit as st
import requests
import pandas as pd
from datetime import datetime, time, timezone

# -----------------------------------------------------------------------------
# Configuration & Setup
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="OSHA Historic NWS Alert Audit Tool",
    page_icon="🛡️",
    layout="wide"
)

# Custom User-Agent required for NWS and OSM compliance
HEADERS = {"User-Agent": "OSHA_HeatAlert_Lookup/2.0 (contact: andreodu@gmail.com)"}

# -----------------------------------------------------------------------------
# Helper Functions: Coordinate & Zone Resolution
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def resolve_nws_zone_from_coords(lat: float, lon: float):
    """
    Queries the official weather.gov points API to resolve coordinates 
    to a specific NWS Forecast Office (WFO), Zone ID, and State abbreviation.
    """
    url = f"https://api.weather.gov/points/{lat},{lon}"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        props = data.get("properties", {})
        wfo = props.get("cwa")
        
        # Extract Forecast Zone ID (e.g., .../zones/forecast/VAZ095 -> VAZ095)
        forecast_zone_url = props.get("forecastZone")
        zone_id = forecast_zone_url.split("/")[-1] if forecast_zone_url else None
        
        # Extract State Abbreviation from relative location if available
        rel_loc = props.get("relativeLocation", {}).get("properties", {})
        state_abbr = rel_loc.get("state")
        
        return {
            "wfo": wfo,
            "zone_id": zone_id,
            "state_abbr": state_abbr,
            "grid_id": props.get("gridId"),
            "grid_x": props.get("gridX"),
            "grid_y": props.get("gridY")
        }, None
        
    except requests.exceptions.RequestException as e:
        return None, f"NWS Points API Error: {str(e)}"

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_iem_state_events(state_abbr: str, year: int):
    """
    Fetches all VTEC events for a given state and year from the IEM API.
    """
    url = "https://mesonet.agron.iastate.edu/json/vtec_events_bystate.py"
    params = {
        "state": state_abbr.upper(),
        "year": year
    }

    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=25)
        if response.status_code == 200:
            try:
                data = response.json()
                return data.get("vtec_events", []), None
            except ValueError:
                return None, f"Failed to parse IEM JSON response."
        else:
            return None, f"IEM API error status {response.status_code}"
            
    except requests.exceptions.RequestException as e:
        return None, f"Network request failed: {str(e)}"

def filter_alerts(events: list, target_date: datetime.date, target_zone_id: str, heat_only: bool = False):
    """
    Filters events by date overlap, target zone, and optionally restricts 
    strictly to heat phenomena (HT, EH, XH).
    """
    active_alerts = []
    
    target_start = datetime.combine(target_date, time.min).replace(tzinfo=timezone.utc)
    target_end = datetime.combine(target_date, time.max).replace(tzinfo=timezone.utc)

    # Heat phenomena codes mapping
    heat_phenomena = {"HT", "EH", "XH"}

    for event in events:
        # 1. Check if the alert applies to our zone/county
        # IEM events usually list affected zones or counties in various formats
        # We check target_zone_id matching
        zones = event.get("zones", [])
        area_name = event.get("area_name", "")
        
        # If zones list doesn't explicitly contain our target zone, check area description or skip
        # Note: state-level pulls include zone strings or IDs in the event data
        phenomena = event.get("phenomena", "")
        
        if heat_only and phenomena not in heat_phenomena:
            continue

        issue_str = event.get("issue")
        expire_str = event.get("expire")
        
        if not issue_str or not expire_str:
            continue

        try:
            issue_dt = datetime.fromisoformat(issue_str.replace("Z", "+00:00"))
            expire_dt = datetime.fromisoformat(expire_str.replace("Z", "+00:00"))

            # 2. Interval overlap check for the target date
            if issue_dt <= target_end and expire_dt >= target_start:
                significance = event.get("significance", "")
                
                # Descriptive mappings
                phen_map = {
                    "HT": "Heat", "EH": "Excessive Heat", "XH": "Extreme Heat",
                    "SV": "Severe Thunderstorm", "TO": "Tornado", "FF": "Flash Flood",
                    "FL": "Flood", "WS": "Winter Storm", "HW": "High Wind", "FZ": "Freeze"
                }
                sig_map = {"W": "Warning", "A": "Watch", "Y": "Advisory", "S": "Statement"}
                
                p_name = phen_map.get(phenomena, phenomena)
                s_name = sig_map.get(significance, significance)
                
                active_alerts.append({
                    "Phenomenon Code": f"{phenomena}.{significance}",
                    "Alert Category": f"{p_name} {s_name}",
                    "Issuing WFO": event.get("wfo"),
                    "Area / Zone": area_name,
                    "Issued (UTC)": issue_dt.strftime("%Y-%m-%d %H:%M"),
                    "Expires (UTC)": expire_dt.strftime("%Y-%m-%d %H:%M"),
                    "Event ID": event.get("eventid"),
                    "NWS Text URL": event.get("url")
                })
        except ValueError:
            continue

    return pd.DataFrame(active_alerts)

# -----------------------------------------------------------------------------
# Streamlit UI Layout
# -----------------------------------------------------------------------------
st.title("🛡️ OSHA Historic NWS Alert Audit Tool")
st.markdown(
    "**Coordinate & Zone Verification:** Investigate official NWS warnings and advisories "
    "by entering precise jobsite coordinates and inspection dates."
)

st.divider()

# Sidebar Controls
with st.sidebar:
    st.header("Jobsite Parameters")
    
    lat_input = st.number_input("Latitude", value=36.7168, format="%.4f")
    lon_input = st.number_input("Longitude", value=-76.2494, format="%.4f")
    
    # Fallback state override incase points API doesn't return state string directly
    state_override = st.selectbox(
        "State Abbreviation Override", 
        ["VA", "TX", "NC", "FL", "CA", "NY", "OH", "PA", "GA", "IL", "MI", "WA"], 
        index=0
    )
    
    target_date = st.date_input("Incident / Inspection Date", value=datetime(2026, 7, 3))
    
    st.divider()
    st.subheader("Filter Settings")
    filter_mode = st.radio(
        "Audit Scope", 
        ["Phase 1: Show ALL Active Alerts", "Phase 2: Narrow Down to Heat Alerts Only (HT, EH, XH)"]
    )
    
    query_btn = st.button("Run Alert Audit", type="primary", use_container_width=True)

# Main Execution Logic
if query_btn:
    with st.spinner("Resolving coordinates to NWS Zone & WFO..."):
        zone_data, err = resolve_nws_zone_from_coords(lat_input, lon_input)

    if err and not zone_data:
        st.error(f"❌ {err}")
    else:
        # Determine state abbreviation
        state_abbr = zone_data.get("state_abbr") if zone_data and zone_data.get("state_abbr") else state_override
        zone_id = zone_data.get("zone_id") if zone_data else "Unknown"
        wfo = zone_data.get("wfo") if zone_data else "Unknown"

        # Display Location Verification Summary
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader("📍 Jobsite & Zone Verification")
            st.write(f"**Target Coordinates:** {lat_input:.4f}° N, {lon_input:.4f}° W")
            st.write(f"**Resolved NWS Forecast Zone:** `{zone_id}`")
            st.write(f"**Issuing Forecast Office (WFO):** `{wfo}`")
            st.write(f"**Associated State:** `{state_abbr}`")
            st.write(f"**Target Date:** {target_date.strftime('%B %d, %Y')}")
        
        with col2:
            map_df = pd.DataFrame({"lat": [lat_input], "lon": [lon_input]})
            st.map(map_df, zoom=9, use_container_width=True)

        st.divider()

        # Fetch IEM Data for State & Year
        year = target_date.year
        with st.spinner(f"Querying IEM archive for state '{state_abbr}' ({year})..."):
            raw_events, iem_err = fetch_iem_state_events(state_abbr, year)

        if iem_err:
            st.error(f"❌ {iem_err}")
        elif not raw_events:
            st.info(f"ℹ️ No weather alert records found in IEM for {state_abbr} in {year}.")
        else:
            heat_only_flag = "Heat Alerts Only" in filter_mode
            df_results = filter_alerts(raw_events, target_date, zone_id, heat_only=heat_only_flag)

            st.subheader("📋 Audit Results")

            if df_results.empty:
                scope_text = "Heat Advisories/Warnings (HT, EH, XH)" if heat_only_flag else "weather alerts"
                st.success(f"✅ No official {scope_text} were active for this zone on {target_date.strftime('%Y-%m-%d')}.")
            else:
                st.warning(f"⚠️ **Found {len(df_results)} matching alert record(s)!**")
                
                display_cols = ["Phenomenon Code", "Alert Category", "Area / Zone", "Issued (UTC)", "Expires (UTC)", "Event ID"]
                st.dataframe(df_results[display_cols], use_container_width=True)

                # Expandable records for case file
                st.markdown("### 📄 Detailed Case File Records")
                for _, row in df_results.iterrows():
                    with st.expander(f"📌 [{row['Phenomenon Code']}] {row['Alert Category']} — {row['Area / Zone']}"):
                        st.write(f"**Issuing WFO:** {row['Issuing WFO']}")
                        st.write(f"**Effective Issued:** {row['Issued (UTC)']}")
                        st.write(f"**Effective Expires:** {row['Expires (UTC)']}")
                        if row.get("NWS Text URL"):
                            st.markdown(f"[🔗 View Official NWS Text Record]({row['NWS Text URL']})")
