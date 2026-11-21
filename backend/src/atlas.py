import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

METHOD='StandardScaler → PCA / svd_solver=full / random_state=42'

def project(spectra):
    if len(spectra)<3:raise ValueError('至少需要三个已测量染样')
    values=np.asarray(spectra,dtype=float)
    if values.ndim!=2 or values.shape[1]!=36:raise ValueError('每条光谱必须为 36 波段')
    if not np.isfinite(values).all():raise ValueError('光谱存在非有限读数')
    scaler=StandardScaler();scaled=scaler.fit_transform(values)
    pca=PCA(n_components=2,svd_solver='full',random_state=42)
    projected=pca.fit_transform(scaled)
    reconstructed=pca.inverse_transform(projected)
    return {'coordinates':projected.tolist(),'explained_variance':pca.explained_variance_ratio_.tolist(),
            'reconstruction_mse':float(np.mean((scaled-reconstructed)**2)),'method':METHOD}

def calculate_atlas(samples):
    result=project([s['spectrum'] for s in samples])
    return {'explained_variance':result['explained_variance'],'reconstruction_mse':result['reconstruction_mse'],
            'points':[{'id':s['id'],'lot':s['lot'],'recipe_id':s['recipe_id'],'x':float(v[0]),'y':float(v[1])} for s,v in zip(samples,result['coordinates'])],
            'count':len(samples),'method':result['method']}
