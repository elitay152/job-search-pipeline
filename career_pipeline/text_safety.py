"""Characters that XML 1.0 cannot represent in editable application documents."""
import re

XML_INVALID = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')
