def fetch_media(post_url):

    try:

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "en-US,en;q=0.9"
        }

        r = requests.get(post_url, headers=headers, timeout=15)

        html = r.text

        # extract JSON from page
        match = re.search(r'__additionalDataLoaded\([^,]+,(.*)\);</script>', html)

        if not match:
            return []

        data = json.loads(match.group(1))

        media = data["items"][0]

        # --------------------
        # CAROUSEL POSTS
        # --------------------
        if "carousel_media" in media:

            items = []

            for m in media["carousel_media"]:

                if m.get("video_versions"):
                    items.append(("video", m["video_versions"][0]["url"]))

                elif m.get("image_versions2"):
                    items.append(("photo", m["image_versions2"]["candidates"][0]["url"]))

            return items


        # --------------------
        # SINGLE VIDEO
        # --------------------
        if media.get("video_versions"):
            return [("video", media["video_versions"][0]["url"])]


        # --------------------
        # SINGLE PHOTO
        # --------------------
        if media.get("image_versions2"):
            return [("photo", media["image_versions2"]["candidates"][0]["url"])]

        return []

    except Exception as e:

        log(f"Media error: {e}")
        return []
