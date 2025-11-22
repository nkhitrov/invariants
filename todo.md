
https://docs.pydantic.dev/latest/concepts/fields/#inspecting-model-fields
https://docs.pydantic.dev/latest/concepts/models/#rootmodel-and-custom-root-types
#     model_config = ConfigDict(frozen=True)
# https://docs.pydantic.dev/latest/concepts/models/#abstract-base-classes
# https://docs.pydantic.dev/latest/concepts/types/#named-type-aliases

# через функцию можно проверять списки на "хотя бы один" или "каждый"
# https://docs.pydantic.dev/latest/concepts/fields/#discriminator
# https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions-with-callable-discriminator

# для вложенных моделей
# https://docs.pydantic.dev/latest/concepts/unions/#nested-discriminated-unions

Payment = PaymentInit | PaymentPending | PaymentSucceeded | PaymentCancelled

# class ProcessPaymentUseCase:
#
#     def execute(self, payment: PaymentInit | PaymentPending) -> PaymentSucceeded | PaymentCancelled:
        p: Payment = self.repo.get()
        match p:
            case PaymentPending:
                ...
                return PaymentSucceeded()



```python
    @classmethod
    def build(cls, *_: Any, **kwargs: Any) -> T:
        """Build an instance of the factory's __model__

        :param kwargs: Any kwargs. If field names are set in kwargs, their values will be used.

        :returns: An instance of type T.

        """
        return cast("T", cls.__model__(**cls.process_kwargs(**kwargs)))
```

по сути надо просто переопределить билд так, чтбы он принимал модель стейта, а отдавал уже инстанс алхимии
тогда дальше оно просто уйдет в session.add

либо переопределить process_kwargs или что-то там глубже, чтобы поля смапить в поля и модели алхимии на самом раннем уровне


фичи
- запрещать юнион с любом типом и None. для None должен быть отдельный статус. сделать приписку, что если полей много, то вам нужна рид модель
- маркер для типа полей которые надо переопределить в стейтах