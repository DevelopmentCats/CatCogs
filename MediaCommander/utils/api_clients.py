"""
API Client classes for MediaCommander cog
Handles communication with Plex, Sonarr, Radarr, Lidarr, Tautulli, and Overseerr
"""

import aiohttp
import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import xml.etree.ElementTree as ET

log = logging.getLogger("red.mediacommander.api_clients")

class BaseAPIClient:
    """Base API client with common functionality"""
    
    def __init__(self, base_url: str, api_key: str = None, headers: Dict[str, str] = None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = headers or {}
        self.session = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout, headers=self.headers)
        return self.session
        
    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request to API"""
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"
        
        try:
            async with session.request(method, url, **kwargs) as response:
                if response.content_type == 'application/json':
                    return await response.json()
                elif response.content_type in ['application/xml', 'text/xml']:
                    text = await response.text()
                    return self._parse_xml(text)
                else:
                    return {"status": response.status, "text": await response.text()}
        except Exception as e:
            log.error(f"API request failed: {e}")
            raise
            
    def _parse_xml(self, xml_text: str) -> Dict[str, Any]:
        """Parse XML response to dict"""
        try:
            root = ET.fromstring(xml_text)
            return self._xml_to_dict(root)
        except ET.ParseError as e:
            log.error(f"Failed to parse XML: {e}")
            return {"error": "Failed to parse XML response"}
            
    def _xml_to_dict(self, element) -> Dict[str, Any]:
        """Convert XML element to dictionary"""
        result = {}
        
        # Add attributes
        if element.attrib:
            result.update(element.attrib)
            
        # Add children
        for child in element:
            child_data = self._xml_to_dict(child)
            if child.tag in result:
                if not isinstance(result[child.tag], list):
                    result[child.tag] = [result[child.tag]]
                result[child.tag].append(child_data)
            else:
                result[child.tag] = child_data
                
        # Add text content
        if element.text and element.text.strip():
            if result:
                result['_text'] = element.text.strip()
            else:
                result = element.text.strip()
                
        return result
        
    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()

class PlexClient(BaseAPIClient):
    """Plex Media Server API client"""
    
    def __init__(self, base_url: str, token: str):
        headers = {'X-Plex-Token': token}
        super().__init__(base_url, api_key=token, headers=headers)
        
    async def get_server_info(self) -> Dict[str, Any]:
        """Get Plex server information"""
        return await self._request('GET', '/')
        
    async def get_libraries(self) -> List[Dict[str, Any]]:
        """Get all libraries"""
        response = await self._request('GET', '/library/sections')
        return response.get('MediaContainer', {}).get('Directory', [])
        
    async def get_users(self) -> List[Dict[str, Any]]:
        """Get all Plex users"""
        response = await self._request('GET', '/accounts')
        return response.get('MediaContainer', {}).get('Account', [])
        
    async def search_media(self, query: str, library_id: str = None) -> List[Dict[str, Any]]:
        """Search for media"""
        endpoint = f'/search?query={query}'
        if library_id:
            endpoint += f'&sectionId={library_id}'
        response = await self._request('GET', endpoint)
        return response.get('MediaContainer', {}).get('Metadata', [])
        
    async def get_sessions(self) -> List[Dict[str, Any]]:
        """Get active sessions"""
        response = await self._request('GET', '/status/sessions')
        return response.get('MediaContainer', {}).get('Metadata', [])
        
    async def invite_user(self, email: str, library_ids: List[str]) -> Dict[str, Any]:
        """Invite user to Plex"""
        data = {
            'friend': email,
            'server_id': await self._get_server_id(),
            'shared': 1,
            'librarySectionIDs': ','.join(library_ids)
        }
        return await self._request('POST', '/api/v2/shared_servers', json=data)
        
    async def _get_server_id(self) -> str:
        """Get server machine identifier"""
        info = await self.get_server_info()
        return info.get('MediaContainer', {}).get('machineIdentifier', '')

class SonarrClient(BaseAPIClient):
    """Sonarr API client"""
    
    def __init__(self, base_url: str, api_key: str):
        headers = {'X-Api-Key': api_key}
        super().__init__(base_url, api_key=api_key, headers=headers)
        
    async def get_series(self) -> List[Dict[str, Any]]:
        """Get all series"""
        return await self._request('GET', '/api/v3/series')
        
    async def search_series(self, term: str) -> List[Dict[str, Any]]:
        """Search for series"""
        return await self._request('GET', f'/api/v3/series/lookup?term={term}')
        
    async def add_series(self, series_data: Dict[str, Any]) -> Dict[str, Any]:
        """Add new series"""
        return await self._request('POST', '/api/v3/series', json=series_data)
        
    async def get_queue(self) -> List[Dict[str, Any]]:
        """Get download queue"""
        response = await self._request('GET', '/api/v3/queue')
        return response.get('records', [])
        
    async def get_calendar(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Get calendar/upcoming episodes"""
        return await self._request('GET', f'/api/v3/calendar?start={start_date}&end={end_date}')
        
    async def search_missing(self, series_id: int = None) -> Dict[str, Any]:
        """Search for missing episodes"""
        data = {'name': 'MissingEpisodeSearch'}
        if series_id:
            data['seriesId'] = series_id
        return await self._request('POST', '/api/v3/command', json=data)

class RadarrClient(BaseAPIClient):
    """Radarr API client"""
    
    def __init__(self, base_url: str, api_key: str):
        headers = {'X-Api-Key': api_key}
        super().__init__(base_url, api_key=api_key, headers=headers)
        
    async def get_movies(self) -> List[Dict[str, Any]]:
        """Get all movies"""
        return await self._request('GET', '/api/v3/movie')
        
    async def search_movies(self, term: str) -> List[Dict[str, Any]]:
        """Search for movies"""
        return await self._request('GET', f'/api/v3/movie/lookup?term={term}')
        
    async def add_movie(self, movie_data: Dict[str, Any]) -> Dict[str, Any]:
        """Add new movie"""
        return await self._request('POST', '/api/v3/movie', json=movie_data)
        
    async def get_queue(self) -> List[Dict[str, Any]]:
        """Get download queue"""
        response = await self._request('GET', '/api/v3/queue')
        return response.get('records', [])
        
    async def get_calendar(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Get calendar/upcoming movies"""
        return await self._request('GET', f'/api/v3/calendar?start={start_date}&end={end_date}')
        
    async def search_missing(self, movie_id: int = None) -> Dict[str, Any]:
        """Search for missing movies"""
        data = {'name': 'MissingMovieSearch'}
        if movie_id:
            data['movieIds'] = [movie_id]
        return await self._request('POST', '/api/v3/command', json=data)

class LidarrClient(BaseAPIClient):
    """Lidarr API client"""
    
    def __init__(self, base_url: str, api_key: str):
        headers = {'X-Api-Key': api_key}
        super().__init__(base_url, api_key=api_key, headers=headers)
        
    async def get_artists(self) -> List[Dict[str, Any]]:
        """Get all artists"""
        return await self._request('GET', '/api/v1/artist')
        
    async def search_artists(self, term: str) -> List[Dict[str, Any]]:
        """Search for artists"""
        return await self._request('GET', f'/api/v1/artist/lookup?term={term}')
        
    async def add_artist(self, artist_data: Dict[str, Any]) -> Dict[str, Any]:
        """Add new artist"""
        return await self._request('POST', '/api/v1/artist', json=artist_data)
        
    async def get_albums(self, artist_id: int = None) -> List[Dict[str, Any]]:
        """Get albums"""
        endpoint = '/api/v1/album'
        if artist_id:
            endpoint += f'?artistId={artist_id}'
        return await self._request('GET', endpoint)
        
    async def search_albums(self, term: str) -> List[Dict[str, Any]]:
        """Search for albums"""
        return await self._request('GET', f'/api/v1/album/lookup?term={term}')

class TautulliClient(BaseAPIClient):
    """Tautulli API client"""
    
    def __init__(self, base_url: str, api_key: str):
        super().__init__(base_url, api_key=api_key)
        
    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Override to add API key as parameter"""
        params = kwargs.get('params', {})
        params['apikey'] = self.api_key
        params['cmd'] = endpoint.lstrip('/')
        kwargs['params'] = params
        
        return await super()._request(method, '/api/v2', **kwargs)
        
    async def get_activity(self) -> Dict[str, Any]:
        """Get current activity"""
        return await self._request('GET', 'get_activity')
        
    async def get_home_stats(self) -> Dict[str, Any]:
        """Get home statistics"""
        return await self._request('GET', 'get_home_stats')
        
    async def get_user_watch_time_stats(self, user_id: int = None) -> Dict[str, Any]:
        """Get user watch time statistics"""
        params = {}
        if user_id:
            params['user_id'] = user_id
        return await self._request('GET', 'get_user_watch_time_stats', params=params)
        
    async def get_plays_by_date(self, time_range: int = 30) -> Dict[str, Any]:
        """Get plays by date"""
        params = {'time_range': time_range}
        return await self._request('GET', 'get_plays_by_date', params=params)
        
    async def get_users(self) -> Dict[str, Any]:
        """Get all users"""
        return await self._request('GET', 'get_users')

class OverseerrClient(BaseAPIClient):
    """Overseerr API client"""
    
    def __init__(self, base_url: str, api_key: str):
        headers = {'X-Api-Key': api_key}
        super().__init__(base_url, api_key=api_key, headers=headers)
        
    async def get_requests(self, take: int = 20, skip: int = 0) -> Dict[str, Any]:
        """Get all requests"""
        params = {'take': take, 'skip': skip}
        return await self._request('GET', '/api/v1/request', params=params)
        
    async def get_pending_requests(self) -> Dict[str, Any]:
        """Get pending requests"""
        params = {'filter': 'pending'}
        return await self._request('GET', '/api/v1/request', params=params)
        
    async def approve_request(self, request_id: int) -> Dict[str, Any]:
        """Approve a request"""
        return await self._request('POST', f'/api/v1/request/{request_id}/approve')
        
    async def decline_request(self, request_id: int, reason: str = None) -> Dict[str, Any]:
        """Decline a request"""
        data = {}
        if reason:
            data['reason'] = reason
        return await self._request('POST', f'/api/v1/request/{request_id}/decline', json=data)
        
    async def search_movies(self, query: str) -> Dict[str, Any]:
        """Search for movies"""
        params = {'query': query}
        return await self._request('GET', '/api/v1/search', params=params)
        
    async def search_tv(self, query: str) -> Dict[str, Any]:
        """Search for TV shows"""
        params = {'query': query}
        return await self._request('GET', '/api/v1/search', params=params)
        
    async def request_movie(self, movie_id: int, user_id: int = None) -> Dict[str, Any]:
        """Request a movie"""
        data = {'mediaId': movie_id, 'mediaType': 'movie'}
        if user_id:
            data['userId'] = user_id
        return await self._request('POST', '/api/v1/request', json=data)
        
    async def request_tv(self, tv_id: int, seasons: List[int] = None, user_id: int = None) -> Dict[str, Any]:
        """Request a TV show"""
        data = {'mediaId': tv_id, 'mediaType': 'tv'}
        if seasons:
            data['seasons'] = seasons
        if user_id:
            data['userId'] = user_id
        return await self._request('POST', '/api/v1/request', json=data) 