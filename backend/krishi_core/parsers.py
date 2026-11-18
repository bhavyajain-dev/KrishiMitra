from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


class ObjectJSONParser(JSONParser):
    """JSON bodies must be objects. Every endpoint reads fields with
    request.data.get(...), so an array or bare value would crash with a 500."""

    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type, parser_context)
        if not isinstance(data, dict):
            raise ParseError("Request body must be a JSON object.")
        return data
