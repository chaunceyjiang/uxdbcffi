import sys
import uxdbcffi


def register():
    sys.modules["uxdb"] = uxdbcffi
