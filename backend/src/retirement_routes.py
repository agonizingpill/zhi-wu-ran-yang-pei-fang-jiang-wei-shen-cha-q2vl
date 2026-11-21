from fastapi import APIRouter,Depends,Query
from .database import session
from .auth import current,editor,admin
from .retirement_schemas import RetirementBatchInput,RetirementRejectInput
from . import retirement_service
router=APIRouter()

@router.get('/retirements')
def batches(user=Depends(current),db=Depends(session)):
    return retirement_service.batch_list(db)

@router.get('/retirements/preview')
def preview(recipe_id:int=Query(gt=0),max_spectral_rms:float=Query(default=retirement_service.DEFAULT_THRESHOLD,gt=0,le=1),
            user=Depends(current),db=Depends(session)):
    return retirement_service.preview(db,recipe_id,max_spectral_rms)

@router.post('/retirements')
def propose(p:RetirementBatchInput,user=Depends(editor),db=Depends(session)):
    return retirement_service._detail(db,retirement_service.propose(db,p,user))

@router.post('/retirements/{key}/confirm')
def confirm(key:int,user=Depends(admin),db=Depends(session)):
    return retirement_service._detail(db,retirement_service.confirm(db,key,user))

@router.post('/retirements/{key}/reject')
def reject(key:int,p:RetirementRejectInput,user=Depends(admin),db=Depends(session)):
    return retirement_service._detail(db,retirement_service.reject(db,key,p,user))

@router.get('/retirement-history')
def history(recipe_id:int|None=Query(default=None,gt=0),user=Depends(current),db=Depends(session)):
    return retirement_service.history(db,recipe_id)
