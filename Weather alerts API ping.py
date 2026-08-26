import json
import sys
from typing import Any, Dict, List
import requests


class WeatherAlertFetcher:
    """Fetches active weather alerts from the National Weather Service (NWS) API."""

    BASE_URL: str = "https://api.weather.gov/alerts/active"

    def __init__(self, user_agent: str) -> None:
        """Initialize the fetcher with a required User-Agent header.

        :param user_agent: Application name and contact info (e.g., 'AlertApp/1.0 contact@example.com')
        """
        self.headers: Dict[str, str] = {
            "User-Agent": user_agent,
            "Accept": "application/geo+json",
        }

    def get_alerts_by_state(self, state_code: str) -> List[Dict[str, Any]]:
        """Fetch active weather alerts for a specific US state or territory.

        :param state_code: Two-letter state abbreviation (e.g., 'VA', 'TX')
        :return: List of parsed alert dictionaries
        """
        params: Dict[str, str] = {"area": state_code.upper()}

        try:
            response = requests.get(
                self.BASE_URL, headers=self.headers, params=params, timeout=10
            )
            response.raise_for_status()
            data: Dict[str, Any] = response.json()
            features: List[Dict[str, Any]] = data.get("features", [])
            return self._parse_features(features)
        except requests.exceptions.RequestException as err:
            print(f"Error fetching state alerts for {state_code}: {err}", file=sys.stderr)
            return []

    def get_alerts_by_coordinates(self, latitude: float, longitude: float) -> List[Dict[str, Any]]:
        """Fetch active weather alerts for a specific geographic coordinate.

        :param latitude: Latitude in decimal degrees
        :param longitude: Longitude in decimal degrees
        :return: List of parsed alert dictionaries
        """
        params: Dict[str, str] = {"point": f"{latitude},{longitude}"}

        try:
            response = requests.get(
                self.BASE_URL, headers=self.headers, params=params, timeout=10
            )
            response.raise_for_status()
            data: Dict[str, Any] = response.json()
            features: List[Dict[str, Any]] = data.get("features", [])
            return self._parse_features(features)
        except requests.exceptions.RequestException as err:
            print(f"Error fetching point alerts: {err}", file=sys.stderr)
            return []

    def _parse_features(self, features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract relevant alert fields from returned GeoJSON features."""
        parsed_alerts: List[Dict[str, Any]] = []

        for feature in features:
            properties = feature.get("properties", {})
            alert_data = {
                "id": properties.get("id"),
                "event": properties.get("event"),
                "severity": properties.get("severity"),
                "certainty": properties.get("certainty"),
                "urgency": properties.get("urgency"),
                "headline": properties.get("headline"),
                "description": properties.get("description"),
                "instruction": properties.get("instruction"),
                "area_description": properties.get("areaDesc"),
                "effective": properties.get("effective"),
                "expires": properties.get("expires"),
            }
            parsed_alerts.append(alert_data)

        return parsed_alerts


def main() -> None:
    user_agent = "WeatherAlertApp/1.0 (contact@example.com)"
    fetcher = WeatherAlertFetcher(user_agent=user_agent)

    print("Fetching active weather alerts for Virginia (VA)...")
    state_alerts = fetcher.get_alerts_by_state("VA")

    if not state_alerts:
        print("No active alerts found or query failed.")
    else:
        print(f"Found {len(state_alerts)} active alert(s):\n")
        for idx, alert in enumerate(state_alerts, start=1):
            print(f"--- Alert #{idx} ---")
            print(f"Event:       {alert['event']}")
            print(f"Severity:    {alert['severity']}")
            print(f"Headline:    {alert['headline']}")
            print(f"Area:        {alert['area_description']}")
            print(f"Expires:     {alert['expires']}")
            print()


if __name__ == "__main__":
    main()
