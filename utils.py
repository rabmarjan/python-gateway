import yaml
import logging
from typing import Dict, List, Optional

def load_routes(routes_file: str = 'routes.yml') -> Dict[str, str]:
    """
    Load and parse routes from YAML configuration
    
    :param routes_file: Path to the routes configuration file
    :return: Dictionary of service names and their URLs
    """
    try:
        # Read the YAML configuration file
        with open(routes_file, 'r') as file:
            config = yaml.safe_load(file)
        
        # Extract routes from the configuration
        routes = config.get('gateway', {}).get('routes', [])
        
        # Create route map with proper URL formatting
        route_map = {}
        for route in routes:
            # Extract service name from route id
            service_name = route.get('id')
            
            # Skip routes without an ID
            if not service_name:
                logging.warning(f"Skipping route without ID: {route}")
                continue
            
            # Add http:// prefix to URI if missing
            uri = route.get('uri', '')
            if not uri:
                logging.warning(f"Skipping route {service_name} with empty URI")
                continue
            
            # Ensure URI has a protocol
            if not uri.startswith(('http://', 'https://')):
                uri = f'http://{uri}'
            
            # Store in route map
            route_map[service_name] = uri
        
        # Log the loaded routes
        logging.info(f"Loaded {len(route_map)} routes from {routes_file}")
        return route_map
    
    except FileNotFoundError:
        logging.error(f"Routes configuration file not found: {routes_file}")
        return {}
    except yaml.YAMLError as e:
        logging.error(f"Error parsing routes configuration: {e}")
        return {}
    except Exception as e:
        logging.error(f"Unexpected error loading routes: {e}")
        return {}

def get_route_predicates(routes_file: str = 'routes.yml') -> List[Dict[str, str]]:
    """
    Extract route predicates from the YAML configuration
    
    :param routes_file: Path to the routes configuration file
    :return: List of route predicate configurations
    """
    try:
        # Read the YAML configuration file
        with open(routes_file, 'r') as file:
            config = yaml.safe_load(file)
        
        # Extract routes from the configuration
        routes = config.get('gateway', {}).get('routes', [])
        
        # Clean and process predicates
        processed_routes = []
        for route in routes:
            # Add http:// prefix to URI if missing
            uri = route.get('uri', '')
            if not uri.startswith(('http://', 'https://')):
                route['uri'] = f'http://{uri}'
            processed_route = {
                'id': route.get('id'),
                'predicates': [],
                'uri': route.get('uri')
            }
            
            # Clean predicates
            for predicate in route.get('predicates', []):
                # Strip spaces around Path= predicate
                if predicate.startswith('Path='):
                    cleaned_predicate = 'Path=' + predicate[5:].strip()
                    processed_route['predicates'].append(cleaned_predicate)
                else:
                    processed_route['predicates'].append(predicate)
            
            processed_routes.append(processed_route)
        
        return processed_routes
    
    except Exception as e:
        logging.error(f"Error extracting route predicates: {e}")
        return []