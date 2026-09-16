from abc import ABC, abstractmethod

class PaymentProvider(ABC):
    @abstractmethod
    def initiate_payment(self, **kwargs): ...

    @abstractmethod
    def check_payment(self, **kwargs): ...

    @abstractmethod
    def handle_callback(self, payload): ...
