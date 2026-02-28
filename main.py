import os
import time
import requests
from datetime import datetime, time as datetime_time
from dotenv import load_dotenv

load_dotenv() # Laad variabelen uit een lokaal .env bestand als dat bestaat

# We need to read environment variables voor de API keys (zodat ze veilig op GitHub staan)
TOMTOM_API_KEY = os.environ.get("TOMTOM_API_KEY")

# Vul hier een unieke naam in voor je kanaal. 
# Bijvoorbeeld je voornaam + een willekeurig getal.
NTFY_TOPIC = "karlo_htc_verkeer_123" 

# Pas deze coördinaten aan naar jouw startpunt (Thuis) en eindpunt (HTC)
# Handige site om dit op te zoeken: https://www.latlong.net/
THUIS_LAT = "51.2758" # Kerk in Nederweert-Eind (Sint-Gerardus Majellakerk)
THUIS_LON = "5.7796"
HTC_LAT = "51.4134"   # High Tech Campus
HTC_LON = "5.4601"

def send_ntfy_message(message, priority="default", title="HTC Verkeersmonitor"):
    """Stuurt een pushbericht naar je telefoon via ntfy.sh"""
    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    
    # Headers geven de notificatie een titel en een prioriteit
    # (Let op: Geen emoji's in de Title zetten, dit veroorzaakt de latin-1 fout)
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": "car,warning"
    }
    try:
        requests.post(url, data=message.encode('utf-8'), headers=headers)
        print("Notificatie verzonden!")
    except Exception as e:
        print(f"Fout bij sturen ntfy bericht: {e}")

def get_route_data(start_lat, start_lon, end_lat, end_lon):
    """Haalt de actuele route-informatie op via TomTom"""
    if not TOMTOM_API_KEY:
        print("TomTom API key mist.")
        return None
        
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{start_lat},{start_lon}:{end_lat},{end_lon}/json"
    params = {
        "key": TOMTOM_API_KEY,
        "traffic": "true",
        "travelMode": "car",
        "sectionType": "traffic" # Vraag TomTom om specifieke verkeersinformatie (zoals ongelukken)
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        # De snelste route is de eerste
        route = data['routes'][0]
        summary = route['summary']
        
        # Bereken vertraging in minuten
        travel_time_sec = summary['travelTimeInSeconds']
        
        # TomTom geeft direct de opgelopen vertraging door in 'trafficDelayInSeconds'
        # Als er geen file is, is deze key soms afwezig, dus we gebruiken .get()
        delay_sec = summary.get('trafficDelayInSeconds', 0)
        delay_min = delay_sec / 60.0
        
        # Check op specifieke incidenten (ongelukken, wegafsluitingen)
        has_accident = False
        if 'sections' in route:
            for section in route['sections']:
                # magnitude 4 = closure, 3 = major (vaak ongeluk), 2 = minor
                if section.get('sectionType') == 'TRAFFIC' and section.get('magnitudeOfDelay', 0) >= 3:
                     has_accident = True
                     break
        
        return {
            "travel_time_min": travel_time_sec / 60.0,
            "delay_min": delay_min,
            "has_accident": has_accident
        }
    except Exception as e:
        print(f"Fout bij ophalen routegegevens: {e}")
        return None

def main():
    print(f"Start file-monitor om {datetime.now().strftime('%H:%M:%S')}")
    
    now = datetime.now()
    
    # Bepaal of het ochtend of middag is
    is_morning = now.hour < 12
    
    if is_morning:
        start_lat, start_lon = THUIS_LAT, THUIS_LON
        end_lat, end_lon = HTC_LAT, HTC_LON
        end_time = datetime_time(6, 40)
        direction_name = "naar de HTC"
        title = "Ochtend Verkeersmonitor"
    else:
        # Middag: we draaien de route om!
        start_lat, start_lon = HTC_LAT, HTC_LON
        end_lat, end_lon = THUIS_LAT, THUIS_LON
        end_time = datetime_time(16, 30) # 16:30 pm (half 5)
        direction_name = "naar Huis"
        title = "Middag Verkeersmonitor"
    
    previous_delay = 0
    check_interval = 180  # We checken elke 3 minuten (180 seconden)
    
    # Optioneel: Stuur een bericht om te testen of het werkt
    # send_ntfy_message(f"Monitor test gestart. Richting: {direction_name}", priority="default", title=title)
    
    while True:
        now = datetime.now()
        
        # Stop als het na de eindtijd is (even uitgeschakeld voor de test vandaag!)
        if now.time() >= end_time:
             print(f"Het is {end_time.strftime('%H:%M')} geweest. Monitor stopt.")
             break
            
        data = get_route_data(start_lat, start_lon, end_lat, end_lon)
        
        if data is not None:
            current_delay = data['delay_min']
            has_accident = data['has_accident']
            print(f"[{now.strftime('%H:%M:%S')}] Rit {direction_name}. Huidige vertraging: {current_delay:.1f} minuten. Ongeluk gemeld: {has_accident}")
            
            # Check 0: Is er net een ongeluk of afsluiting gebeurd? (ongeacht de lengte van de file)
            if has_accident:
                msg = f"Ongeval / Wegafsluiting gedetecteerd op je route {direction_name}! Huidige vertraging is nu {current_delay:.1f} minuten. Neem mogelijk een andere weg!"
                send_ntfy_message(msg, priority="urgent", title=title) # Urgent overstemt in ntfy soms "Niet Storen"
                
            # Check 1: Neemt de file ineens heel snel toe? (meer dan 10 min gegroeid sinds de vorige check)
            elif (current_delay - previous_delay) > 10:
                msg = f"De vertraging {direction_name} neemt erg snel toe.\n+{current_delay - previous_delay:.1f} min t.o.v. zojuist.\nTotale vertraging nu: {current_delay:.1f} minuten."
                send_ntfy_message(msg, priority="high", title=title)
                
            # Check 2: Gewoon een hele flinke file in het algemeen (groter dan 15 minuten)
            elif current_delay > 15 and previous_delay <= 15:
                msg = f"Veel vertraging! Je hebt nu {current_delay:.1f} minuten vertraging {direction_name}."
                send_ntfy_message(msg, priority="high", title=title)
                
            previous_delay = current_delay
            
        # Wacht 3 minuten voor de volgende check
        time.sleep(check_interval)

if __name__ == "__main__":
    main()
