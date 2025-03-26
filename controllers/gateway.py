import io
import asyncio
from fastapi import Request
from fastapi.responses import StreamingResponse, JSONResponse
from ..services.cache import CacheManager
from ..services.http_client import HttpClientManager
from ..middleware.logging import log_request_body
import yaml
from urllib.parse import urljoin
import logging

class GatewayController:
    """Controller for handling gateway requests"""
    def __init__(self, cache_manager: CacheManager, http_client: HttpClientManager, route_map: dict, cache_ttl: int, routes_file='routes.yml'):
        self.cache_manager = cache_manager
        self.http_client = http_client
        self.route_map = route_map
        self.cache_ttl = cache_ttl
        self.routes = self._load_routes(routes_file)
        
    def _load_routes(self, routes_file):
        """
        Load and parse routes from YAML configuration
        
        :param routes_file: Path to the routes configuration file
        :return: List of route configurations
        """
        try:
            with open(routes_file, 'r') as file:
                config = yaml.safe_load(file)
            
            routes = config.get('gateway', {}).get('routes', [])
            
            # Ensure each route has a properly formatted URI and clean predicates
            for route in routes:
                # Add http:// prefix to URI if missing
                uri = route.get('uri', '')
                if not uri.startswith(('http://', 'https://')):
                    route['uri'] = f'http://{uri}'
                
                # Clean and process predicates
                cleaned_predicates = []
                for predicate in route.get('predicates', []):
                    # Strip spaces around Path= predicate
                    if predicate.startswith('Path='):
                        # Remove spaces between Path= and the actual path
                        cleaned_predicate = 'Path=' + predicate[5:].strip()
                        cleaned_predicates.append(cleaned_predicate)
                    else:
                        cleaned_predicates.append(predicate)
                
                route['predicates'] = cleaned_predicates
            
            return routes
        except Exception as e:
            logging.error(f"Error loading routes configuration: {str(e)}")
            return []
    
    async def proxy_request(self, request: Request, service_url: str):
        """Forward request to microservice with caching for GET requests"""
        req_method = request.method
        path = request.url.path
        req_url = f"{service_url}{path}"
        
        # Prepare headers (forward needed headers)
        headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in ("host", "connection", "content-length")
        }
        
        # Cache key based on URL and any query parameters
        cache_key = f"cache:{path}{request.url.query}"
        
        # Try cache for GET requests
        if req_method == "GET":
            cached_response = await self.cache_manager.get(cache_key)
            if cached_response:
                return JSONResponse(content=cached_response)
        
        # For POST/PUT requests, read body
        body = await request.body() if req_method in ("POST", "PUT", "PATCH") else None
        
        # If body logging is needed for non-GET requests
        if body and req_method != "GET":
            asyncio.create_task(log_request_body(body))
        
        # Forward request to microservice
        response = await self.http_client.request(
            method=req_method,
            url=req_url,
            headers=headers,
            data=body
        )
        
        # Cache GET responses
        if req_method == "GET" and response.status_code == 200:
            try:
                response_data = response.json()
                await self.cache_manager.set(cache_key, response_data, self.cache_ttl)
                return JSONResponse(content=response_data)
            except Exception as e:
                # If JSON parsing fails, return streaming response
                print(f"Error parsing JSON: {e}")
        
        # For non-GET requests or failed JSON parsing, return StreamingResponse
        return StreamingResponse(
            io.BytesIO(response.content),
            status_code=response.status_code,
            headers=dict(response.headers)
        ) 
    
    async def process_request(self, full_path: str, request: Request):
        """Process gateway request and route to appropriate service"""
        
        try:
            # Find matching route based on path predicates
            service_url = None
            for route in self.routes:
                predicates = route.get('predicates', [])
                for predicate in predicates:
                    if predicate.startswith('Path='):
                        path_pattern = predicate[5:].strip()  # Extract path after 'Path='
                        
                        # Remove trailing slash if present for comparison
                        if path_pattern.endswith('/'):
                            path_pattern = path_pattern[:-1]
                        
                        # Check if the full_path matches the predicate
                        if full_path.startswith(path_pattern.strip('/')):
                            service_url = route.get('uri')
                            print(f"Found route for path: {full_path} -> {service_url}")
                            logging.info(f"Routing request to {service_url} based on path: {full_path}")
                            break
                
                if service_url:
                    break
            
            # Default handling if no route matched
            if not service_url:
                logging.warning(f"No route found for path: {full_path}, using default fallback")
                # You might want to implement a default fallback or return a 404
                return await self.return_not_found(request)
                
            # Forward request to microservice
            return await self.proxy_request(request, service_url)
        
        except Exception as e:
            logging.error(f"Error processing gateway request: {str(e)}")
            return await self.return_error(request, str(e))
    
    async def return_not_found(self, request):
    # Implementation depends on your framework
       return {"status": 404, "message": "Resource not found"}

    async def return_error(self, request, error_message):
    # Implementation depends on your framework
       return {"status": 500, "message": f"Gateway error: {error_message}"}
   
    async def invalidate_cache(self, path: str):
        """Invalidate cache entries related to a modified resource"""
        base_path = path.split("/")[0]  # Get resource type
        await self.cache_manager.invalidate(base_path)
