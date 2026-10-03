import os as _os

__version__ = "0.7.0"

# Must run before numpy is imported anywhere: OpenBLAS/OpenMP otherwise start one worker
# thread per CPU core with ~24 MB committed memory each (≈750 MB, 23 threads on 32 cores).
# The app does no heavy linear algebra, so one thread is plenty.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ.setdefault(_var, "1")
