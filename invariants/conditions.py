from typing import Any

from pydantic import AfterValidator


class ContainsOne(AfterValidator):
    required_type: type

    def __init__(self, obj: Any):
        super().__init__(self.validator(obj))
        object.__setattr__(self, "required_type", obj)

    @staticmethod
    def validator(obj: Any) -> Any:
        def validate(value: Any) -> Any:
            if not any(o for o in value if isinstance(o, obj)):
                raise ValueError(f"must contains one or more item of type `{obj}`")
            return value

        return validate
