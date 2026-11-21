from pydantic import BaseModel,Field,ConfigDict,field_validator
class RetirementBatchInput(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False)
    recipe_id:int=Field(gt=0)
    max_spectral_rms:float=Field(default=.005,gt=0,le=1)
    @field_validator('max_spectral_rms')
    @classmethod
    def sane(cls,v):
        if not v>0:raise ValueError('原光谱差距门限必须大于 0')
        return v
class RetirementRejectInput(BaseModel):
    reason:str=Field(min_length=5,max_length=600)
    @field_validator('reason')
    @classmethod
    def meaningful(cls,v):
        if not v.strip():raise ValueError('退回原因不可为空白')
        return v.strip()
