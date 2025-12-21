import extruct
import requests
import pprint
from w3lib.html import get_base_url

pp = pprint.PrettyPrinter(indent=2)
r = requests.get("https://www.alternate.be/CPUs")
base_url = get_base_url(r.text, r.url)
data = extruct.extract(r.text, base_url=base_url)

pp.pprint(data)
