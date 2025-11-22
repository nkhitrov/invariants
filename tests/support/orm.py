import sys
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer, Table,
)
from sqlalchemy.orm import DeclarativeBase,relationship
from sqlalchemy.orm import  Mapped
from sqlalchemy.orm import declared_attr

class Base(DeclarativeBase):
    __abstract__ = True
