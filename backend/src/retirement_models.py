from sqlalchemy import String,Float,ForeignKey,JSON,CheckConstraint,DateTime,UniqueConstraint,func
from sqlalchemy.orm import Mapped,mapped_column
from .database import Base
class RetirementBatch(Base):
    __tablename__='retirement_batches'
    __table_args__=(CheckConstraint('max_spectral_rms>0'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    recipe_id:Mapped[int]=mapped_column(ForeignKey('dye_recipes.id'))
    state:Mapped[str]=mapped_column(String(20),default='proposed')
    max_spectral_rms:Mapped[float]=mapped_column(Float)
    method:Mapped[str]=mapped_column(String(240))
    analysis:Mapped[dict]=mapped_column(JSON)
    created_by:Mapped[str]=mapped_column(String(120))
    created_at:Mapped[object]=mapped_column(DateTime,server_default=func.now())
    reviewed_by:Mapped[str]=mapped_column(String(120),default='')
    reviewed_at:Mapped[object|None]=mapped_column(DateTime,nullable=True)
    rejection_reason:Mapped[str]=mapped_column(String(600),default='')
class RetirementItem(Base):
    __tablename__='retirement_items'
    __table_args__=(UniqueConstraint('batch_id','swatch_id'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    batch_id:Mapped[int]=mapped_column(ForeignKey('retirement_batches.id'))
    swatch_id:Mapped[int]=mapped_column(ForeignKey('swatches.id'))
    substitute_swatch_id:Mapped[int]=mapped_column(ForeignKey('swatches.id'))
    pca_distance:Mapped[float]=mapped_column(Float)
    spectral_rms:Mapped[float]=mapped_column(Float)
    state:Mapped[str]=mapped_column(String(20),default='proposed')
    reject_reason:Mapped[str]=mapped_column(String(300),default='')
class SwatchRetirement(Base):
    __tablename__='swatch_retirements'
    id:Mapped[int]=mapped_column(primary_key=True)
    batch_id:Mapped[int]=mapped_column(ForeignKey('retirement_batches.id'))
    # A swatch can be retired exactly once, even if two confirmations race.
    swatch_id:Mapped[int]=mapped_column(ForeignKey('swatches.id'),unique=True)
    substitute_swatch_id:Mapped[int]=mapped_column(ForeignKey('swatches.id'))
    pca_distance:Mapped[float]=mapped_column(Float)
    spectral_rms:Mapped[float]=mapped_column(Float)
    threshold:Mapped[float]=mapped_column(Float)
    evidence:Mapped[dict]=mapped_column(JSON)
    confirmed_by:Mapped[str]=mapped_column(String(120))
    confirmed_at:Mapped[object]=mapped_column(DateTime,server_default=func.now())
