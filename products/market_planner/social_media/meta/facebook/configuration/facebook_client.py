import os
import requests
from typing import Dict, Any, Optional
from shared.logger.log import setup_logger
import time


from shared.utils.constants import constants

# logger = setup_logger("marketing-app")


class FacebookClient:

    def __init__(self, token: Optional[str] = None):
        self.token = token
        self.base_url = constants.FACEBOOK_GRAPH_URL

        # logger.debug(
        #     "[FB_CLIENT_INIT] token_present=%s",
        #     bool(token)
        # )

    # ---------------- HTTP METHODS ---------------- #

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:

        start = time.time()

        params = params or {}

        if self.token and "access_token" not in params:
            params["access_token"] = self.token

        safe_params = {k: ("****" if "token" in k else v) for k, v in params.items()}

        # logger.info(
        #     "[FB_GET_START] endpoint=%s params=%s",
        #     endpoint,
        #     safe_params
        # )

        try:

            response = requests.get(
                f"{self.base_url}/{endpoint}",
                params=params,
                timeout=30
            )

            duration = round(time.time() - start, 3)

            # logger.info(
            #     "[FB_GET_RESPONSE] endpoint=%s status=%s duration=%ss",
            #     endpoint,
            #     response.status_code,
            #     duration
            # )

            data = response.json()

            if "error" in data:
                # logger.error(
                #     "[FB_GET_ERROR] endpoint=%s error=%s",
                #     endpoint,
                #     data["error"]
                # )
                pass

            else:
                # logger.debug(
                #     "[FB_GET_SUCCESS] endpoint=%s keys=%s",
                #     endpoint,
                #     list(data.keys())
                # )
                pass

            return data

        except Exception as e:

            # logger.exception(
            #     "[FB_GET_EXCEPTION] endpoint=%s error=%s",
            #     endpoint,
            #     str(e)
            # )
        

            raise


    def _post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:

        start = time.time()

        params = params or {}

        if self.token and "access_token" not in params:
            params["access_token"] = self.token

        safe_params = {k: ("****" if "token" in k else v) for k, v in params.items()}
        safe_data = {k: ("****" if "token" in k else v) for k, v in (data or {}).items()}

        # logger.info(
        #     "[FB_POST_START] endpoint=%s params=%s data=%s",
        #     endpoint,
        #     safe_params,
        #     safe_data
        # )

        try:

            response = requests.post(
                f"{self.base_url}/{endpoint}",
                data=data,
                params=params,
                timeout=30
            )

            duration = round(time.time() - start, 3)

            # logger.info(
            #     "[FB_POST_RESPONSE] endpoint=%s status=%s duration=%ss",
            #     endpoint,
            #     response.status_code,
            #     duration
            # )

            data = response.json()

            if "error" in data:
                # logger.error(
                #     "[FB_POST_ERROR] endpoint=%s error=%s",
                #     endpoint,
                #     data["error"]
                # )
                pass
            else:
                # logger.debug(
                #     "[FB_POST_SUCCESS] endpoint=%s keys=%s",
                #     endpoint,
                #     list(data.keys())
                # )
                pass

            return data

        except Exception as e:

            # logger.exception(
            #     "[FB_POST_EXCEPTION] endpoint=%s error=%s",
            #     endpoint,
            #     str(e)
            # )

            raise


    def _delete(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:

        start = time.time()

        params = params or {}

        if self.token and "access_token" not in params:
            params["access_token"] = self.token

        safe_params = {k: ("****" if "token" in k else v) for k, v in params.items()}

        # logger.info(
        #     "[FB_DELETE_START] endpoint=%s params=%s",
        #     endpoint,
        #     safe_params
        # )

        try:

            response = requests.delete(
                f"{self.base_url}/{endpoint}",
                params=params,
                timeout=30
            )

            duration = round(time.time() - start, 3)

            # logger.info(
            #     "[FB_DELETE_RESPONSE] endpoint=%s status=%s duration=%ss",
            #     endpoint,
            #     response.status_code,
            #     duration
            # )

            data = response.json()

            if "error" in data:
                # logger.error(
                #     "[FB_DELETE_ERROR] endpoint=%s error=%s",
                #     endpoint,
                #     data["error"]
                # )
                pass

            return data

        except Exception as e:

            # logger.exception(
            #     "[FB_DELETE_EXCEPTION] endpoint=%s error=%s",
            #     endpoint,
            #     str(e)
            # )

            raise


    # ---------------- TOKEN EXCHANGE ---------------- #

    @staticmethod
    def exchange_code_for_token(code: str) -> Dict[str, Any]:
        start_time = time.time()
        url = f"{constants.FACEBOOK_GRAPH_URL}/oauth/access_token"

        params = {
            "client_id": constants.APP_ID,
            "redirect_uri": constants.REDIRECT_URI,
            "client_secret": constants.APP_SECRET,
            "code": code
        }

        # logger.info(
        #     "[FB_TOKEN_EXCHANGE_REQUEST] url=%s redirect_uri=%s",
        #     url,
        #     REDIRECT_URI,
        # )

        try:
            response = requests.get(url, params=params)

            duration = time.time() - start_time

            # logger.info(
            #     "[FB_TOKEN_EXCHANGE_RESPONSE] status=%s duration=%.3fs",
            #     response.status_code,
            #     duration
            # )

            data = response.json()

            if response.status_code != 200:
                # logger.error(
                #     "[FB_TOKEN_EXCHANGE_ERROR] status=%s response=%s",
                #     response.status_code,
                #     data
                # )
                pass
            else:
                # logger.info(
                #     "[FB_TOKEN_EXCHANGE_SUCCESS] keys=%s",
                #     list(data.keys())
                # )
                pass

            return data

        except Exception as e:
            # logger.exception(
            #     "[FB_TOKEN_EXCHANGE_EXCEPTION] redirect_uri=%s error=%s",
            #     REDIRECT_URI,
            #     str(e)
            # )
            raise


    @staticmethod
    def exchange_for_long_lived_token(short_token: str) -> Dict[str, Any]:

        # logger.info("[FB_LONG_TOKEN_EXCHANGE_START]")

        url = f"{constants.FACEBOOK_GRAPH_URL}/oauth/access_token"

        params = {
            "grant_type": "fb_exchange_token",
            "client_id": constants.APP_ID,
            "client_secret": constants.APP_SECRET,
            "fb_exchange_token": short_token
        }

        start = time.time()

        response = requests.get(url, params=params)

        duration = round(time.time() - start, 3)

        # logger.info(
        #     "[FB_LONG_TOKEN_RESPONSE] status=%s duration=%ss",
        #     response.status_code,
        #     duration
        # )

        data = response.json()

        if "error" in data:
            # logger.error("[FB_LONG_TOKEN_ERROR] %s", data["error"])
            pass

        return data


    # ---------------- API METHODS ---------------- #

    def get_me(self, fields: str = "id") -> Dict[str, Any]:
        # logger.info("[FB_GET_ME] fields=%s", fields)
        return self._get("me", params={"fields": fields})


    def get_accounts(self, fields: str = "name,id,access_token") -> Dict[str, Any]:
        # logger.info("[FB_GET_ACCOUNTS] fields=%s", fields)
        return self._get("me/accounts", params={"fields": fields})


    def get_page_picture(self, page_id: str) -> Dict[str, Any]:
        # logger.info("[FB_GET_PAGE_PICTURE] page_id=%s", page_id)
        return self._get(
            f"{page_id}/picture",
            params={"type": "normal", "redirect": "false"}
        )


    def publish_fb_post(self, page_id: str, message: Optional[str] = None, image_url: Optional[str] = None) -> Dict[str, Any]:

        # logger.info(
        #     "[FB_PUBLISH_POST] page_id=%s has_image=%s",
        #     page_id,
        #     bool(image_url)
        # )

        if image_url:
            endpoint = f"{page_id}/photos"
            data = {"url": image_url, "caption": message or ""}
        else:
            endpoint = f"{page_id}/feed"
            data = {"message": message}

        return self._post(endpoint, data=data)


    def create_ig_media(self, ig_id: str, image_url: str, caption: str = "") -> Dict[str, Any]:

        # logger.info(
        #     "[IG_CREATE_MEDIA] ig_id=%s image_present=%s",
        #     ig_id,
        #     bool(image_url)
        # )

        return self._post(
            f"{ig_id}/media",
            data={"image_url": image_url, "caption": caption}
        )


    def get_media_status(self, media_id: str) -> Dict[str, Any]:

        # logger.info("[IG_MEDIA_STATUS_CHECK] media_id=%s", media_id)

        return self._get(
            media_id,
            params={"fields": "status_code"}
        )


    def publish_ig_media(self, ig_id: str, creation_id: str) -> Dict[str, Any]:

        # logger.info(
        #     "[IG_PUBLISH_MEDIA] ig_id=%s creation_id=%s",
        #     ig_id,
        #     creation_id
        # )

        return self._post(
            f"{ig_id}/media_publish",
            data={"creation_id": creation_id}
        )


    def delete_platform_post(self, post_id: str) -> Dict[str, Any]:

        # logger.info("[FB_DELETE_POST] post_id=%s", post_id)

        return self._delete(post_id)


    def get_post(self, post_id: str, fields: str = "id,message,created_time") -> Dict[str, Any]:

        # logger.info("[FB_GET_POST] post_id=%s fields=%s", post_id, fields)

        return self._get(post_id, params={"fields": fields})


    def update_post_message(self, post_id: str, message: str) -> Dict[str, Any]:

        # logger.info("[FB_UPDATE_POST] post_id=%s", post_id)

        return self._post(post_id, data={"message": message})


    def get_page_posts(
        self,
        page_id: str,
        fields: str = "id,message,created_time,permalink_url,full_picture",
        limit: int = 10
    ) -> Dict[str, Any]:

        # logger.info(
        #     "[FB_GET_PAGE_POSTS] page_id=%s limit=%s",
        #     page_id,
        #     limit
        # )

        return self._get(
            f"{page_id}/posts",
            params={"fields": fields, "limit": limit}
        )