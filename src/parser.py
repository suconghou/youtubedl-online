from urlparse import parse_qsl, urlsplit
import json
import re
import req
import traceback

baseURL = "https://www.youtube.com"
videoPageHost = baseURL + "/watch?v={}&spf=prefetch"
videoInfoHost = baseURL + "/get_video_info?video_id={}"


class infoGetter:

    def parse(self, itagURL=None):
        self.info = {
            "id": self.videoDetails.get("videoId"),
            "title": self.title,
            "duration": self.videoDetails.get("lengthSeconds"),
            "author": self.videoDetails.get("author")
        }
        streams = {}
        for item in self.streamingData.get("formats"):
            itag = item.get("itag")
            s = {
                "quality": item.get("qualityLabel", item.get("quality")),
                "type": item.get("mimeType"),
                "itag": itag,
                "len": item.get("contentLength"),
            }
            if itagURL == itag:
                s["url"] = self.buildURL(item)
            streams[itag] = s

        for item in self.streamingData.get("adaptiveFormats"):
            itag = item.get("itag")
            s = {
                "quality": item.get("qualityLabel", item.get("quality")),
                "type": item.get("mimeType"),
                "itag": itag,
                "len": item.get("contentLength"),
                "initRange":   item.get("initRange", {}),
                "indexRange": item.get("indexRange", {}),
            }
            if itagURL == itag:
                s["url"] = self.buildURL(item)
            streams[itag] = s
        self.info['streams'] = streams
        return self.info

    def buildURL(self, item):
        url = item.get("url")
        if url:
            return url
        url = item.get("cipher")
        if not url:
            raise ValueError("not found url or cipher")
        u = dict(parse_qsl(url))
        url = u.get("url")
        if not url:
            raise ValueError("can not parse url")
        return url+self.signature(u)

    def signature(self, u):
        sp = u.get("sp", "signature")
        if u.get("s"):
            if not self.jsPath:
                raise ValueError("jsPath not found")
            sig = decipher(self.jsPath).decode(u.get("s"))
            return "&{}={}".format(sp, sig)
        elif u.get("sig"):
            return "&{}={}".format(sp, u.get("sig"))
        else:
            raise ValueError("can not decode")


class videoParser:
    def __init__(self, vid):
        try:
            self.parser = pageParser(vid)
        except Exception as e:
            print(str(e) + ' , try infoParser')
            self.parser = infoParser(vid)

    def info(self):
        return self.parser.parse()

    def infoPart(self, itag):
        info = self.parser.parse(itag)
        itagInfo = info.get("streams").get(itag)
        if not itagInfo:
            raise ValueError("itag {} not found".format(itag))
        return {
            'url': itagInfo.get('url')
        }


class pageParser(infoGetter):
    def __init__(self, vid):
        videoPageData = json.loads(req.fetch(videoPageHost.format(vid), 600))
        jsPath = None
        title = None
        player_response = None
        for item in videoPageData:
            if not isinstance(item, dict):
                continue
            if item.has_key("title") and item.has_key("data"):
                title = item.get("title")
                data = item.get("data")
                player_response = json.loads(
                    data["swfcfg"]["args"]["player_response"])
                jsPath = data["swfcfg"]["assets"]["js"]
        if not player_response or not title or not jsPath:
            raise ValueError("not found player_response")
        if not player_response.has_key("streamingData") or not player_response.has_key("videoDetails"):
            raise ValueError("invalid player_response")
        self.title = title
        self.jsPath = jsPath
        self.videoDetails = player_response.get("videoDetails")
        self.streamingData = player_response.get("streamingData")
        req.cache.set("jsPath", self.jsPath, 604800)


class infoParser(infoGetter):
    def __init__(self, vid):
        videoInfoData = dict(
            parse_qsl(req.fetch(videoInfoHost.format(vid), 600)))
        status = videoInfoData.get("status")
        if status != "ok":
            raise ValueError("{}:code {},reason {}".format(status, videoInfoData.get(
                "errorcode"), videoInfoData.get("reason")))
        player_response = json.loads(videoInfoData.get("player_response"))
        if not player_response:
            raise ValueError("empty player_response")

        self.videoDetails = player_response.get("videoDetails")
        self.streamingData = player_response.get("streamingData")

        self.title = self.videoDetails.get("title")
        self.jsPath = req.cache.get("jsPath")


class decipher:
    '''
        https://github.com/rylio/ytdl/blob/master/signature.go
    '''

    def __init__(self, jsPath):
        bodystr = req.fetch(baseURL+jsPath, 604800)
        objResult = re.search(r'var ([a-zA-Z_\$][a-zA-Z_0-9]*)=\{((?:(?:[a-zA-Z_\$][a-zA-Z_0-9]*:function\(a\)\{(?:return )?a\.reverse\(\)\}|[a-zA-Z_\$][a-zA-Z_0-9]*:function\(a,b\)\{return a\.slice\(b\)\}|[a-zA-Z_\$][a-zA-Z_0-9]*:function\(a,b\)\{a\.splice\(0,b\)\}|[a-zA-Z_\$][a-zA-Z_0-9]*:function\(a,b\)\{var c=a\[0\];a\[0\]=a\[b(?:%a\.length)?\];a\[b(?:%a\.length)?\]=c(?:;return a)?\}),?\n?)+)\};', bodystr)
        if not objResult:
            raise ValueError("objResult not match")
        funcResult = re.search(
            r'function(?: [a-zA-Z_\$][a-zA-Z_0-9]*)?\(a\)\{a=a\.split\(""\);\s*((?:(?:a=)?[a-zA-Z_\$][a-zA-Z_0-9]*\.[a-zA-Z_\$][a-zA-Z_0-9]*\(a,\d+\);)+)return a\.join\(""\)\}', bodystr)
        if not funcResult:
            raise ValueError("funcResult not match")
        obj = objResult.group(1).replace('$', '\\$')
        objBody = objResult.group(2).replace('$', '\\$')
        funcBody = funcResult.group(1).replace('$', '\\$')
        result = re.search(
            r'(?:^|,)([a-zA-Z_\$][a-zA-Z_0-9]*):function\(a\)\{(?:return )?a\.reverse\(\)\}', objBody, re.MULTILINE)
        reverseKey = result.group(1).replace('$', '\\$') if result else ''
        result = re.search(
            r'(?:^|,)([a-zA-Z_\$][a-zA-Z_0-9]*):function\(a,b\)\{return a\.slice\(b\)\}', objBody, re.MULTILINE
        )
        sliceKey = result.group(1).replace('$', '\\$') if result else ''
        result = re.search(
            r'(?:^|,)([a-zA-Z_\$][a-zA-Z_0-9]*):function\(a,b\)\{a\.splice\(0,b\)\}', objBody, re.MULTILINE)
        spliceKey = result.group(1).replace('$', '\\$') if result else ''
        result = re.search(
            r'(?:^|,)([a-zA-Z_\$][a-zA-Z_0-9]*):function\(a,b\)\{var c=a\[0\];a\[0\]=a\[b(?:%a\.length)?\];a\[b(?:%a\.length)?\]=c(?:;return a)?\}', objBody, re.MULTILINE)
        swapKey = result.group(1).replace('$', '\\$') if result else ''

        regex = '(?:a=)?%s\\.(%s)\\(a,(\\d+)\\)' % (obj,
                                                    '|'.join(x for x in [reverseKey, sliceKey, spliceKey, swapKey] if x))

        result = re.findall(regex, funcBody)
        if not result:
            raise ValueError("result not match")
        tokens = []
        for item in result:
            if item[0] == swapKey:
                tokens.append('w'+item[1])
            elif item[0] == reverseKey:
                tokens.append("r")
            elif item[0] == sliceKey:
                tokens.append('s'+item[1])
            elif item[0] == spliceKey:
                tokens.append('p'+item[1])
        self.tokens = tokens

    def decode(self, sig):
        tokens = self.tokens
        sig = [x for x in sig]
        pos = 0
        for tok in tokens:
            if len(tok) > 1:
                pos = int(tok[1:])
            if tok[0] == "r":
                sig.reverse()
            elif tok[0] == "w":
                s = sig[0]
                sig[0] = sig[pos]
                sig[pos] = s
            elif tok[0] == "s":
                sig = sig[pos:]
            elif tok[0] == 'p':
                sig = sig[pos:]
        return ''.join(sig)