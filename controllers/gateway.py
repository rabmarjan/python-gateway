import io
from fastapi import Request
from fastapi.responses import StreamingResponse, JSONResponse
from ..services.cache import CacheManager
from ..services.http_client import HttpClientManager
from ..utils import get_route_predicates
import yaml
import logging
import asyncio
from typing import Optional

class GatewayController:
    """Enhanced controller for handling gateway requests with performance optimizations"""
    def __init__(self, cache_manager: CacheManager, http_client: HttpClientManager, route_map: dict, cache_ttl: int = 60, routes_file='routes.yml'):
        self.cache_manager = cache_manager
        self.http_client = http_client
        self.route_map = route_map
        self.cache_ttl = cache_ttl
        self.routes = self._load_routes(routes_file)
        self.routes_lock = asyncio.Lock()
        
    def _load_routes(self, routes_file):
        """
        Load and parse routes from YAML configuration with enhanced error handling
        """
        try:
            with open(routes_file, 'r') as file:
                config = yaml.safe_load(file)
            
            routes = config.get('gateway', {}).get('routes', [])
            
            # Preprocess routes for faster matching
            for route in routes:
                # Normalize predicates
                route['normalized_predicates'] = [
                    predicate.split('=')[1].strip() if '=' in predicate else predicate 
                    for predicate in route.get('predicates', [])
                ]
                
                # Ensure URI has protocol
                if not route.get('uri', '').startswith(('http://', 'https://')):
                    route['uri'] = f'http://{route["uri"]}'
            
            return routes
        except Exception as e:
            logging.error(f"Routes configuration error: {e}")
            return []

    async def proxy_request(self, request: Request, service_url: str) -> Optional[StreamingResponse]:
        """Enhanced proxy request with optimized caching"""
        req_method = request.method
        path = request.url.path
        query = request.url.query
        req_url = f"{service_url}{path}"
        
        # Create a comprehensive cache key
        cache_key = f"gateway_cache:{req_method}:{path}:{query}"
        
        # Try cache for GET requests
        if req_method == "GET":
            cached_response = await self.cache_manager.get(cache_key)
            if cached_response:
                return JSONResponse(content=cached_response)
        
        # For POST/PUT requests, read body efficiently
        body = await request.body() if req_method in ("POST", "PUT", "PATCH") else None
        
        # Prepare headers safely
        headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in ("host", "connection", "content-length")
        }
        
        # Forward request to microservice
        try:
            response = await self.http_client.request(
                method=req_method,
                url=req_url,
                headers=headers,
                data=body
            )
            
            # Cache GET responses with success status
            if req_method == "GET" and response.status_code == 200:
                try:
                    response_data = response.json()
                    # Asynchronously cache the response
                    asyncio.create_task(
                        self.cache_manager.set(cache_key, response_data, self.cache_ttl)
                    )
                    return JSONResponse(content=response_data)
                except Exception as e:
                    logging.warning(f"JSON parsing error: {e}")
            
            # Fallback for non-GET or non-JSON responses
            return StreamingResponse(
                io.BytesIO(response.content),
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        
        except Exception as e:
            logging.error(f"Proxy request error: {e}")
            return None

    async def process_request(self, full_path: str, request: Request):
        """Enhanced request processing with route matching optimization"""
        try:
            # Find matching route using fast path matching
            service_url = None
            for route in self.routes:
                for predicate in route.get('normalized_predicates', []):
                    if full_path.startswith(predicate.strip('/')):
                        service_url = route.get('uri')
                        logging.info(f"Routing {full_path} to {service_url}")
                        break
                
                if service_url:
                    break
            
            # Handle unmatched routes
            if not service_url:
                logging.warning(f"No route found for {full_path}")
                return {"status": 404, "message": "No route found"}
            
            # Forward request
            return await self.proxy_request(request, service_url)
        
        except Exception as e:
            logging.error(f"Request processing error: {e}")
            return {"status": 500, "message": f"Gateway error: {e}"}

    async def invalidate_cache(self, path: str):
        """Invalidate cache entries efficiently"""
        base_path = path.split("/")[0]
        await self.cache_manager.invalidate(base_path)