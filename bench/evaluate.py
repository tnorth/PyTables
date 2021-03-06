import sys
from time import time

import numpy as np
import tables as tb
import tables.numexpr as ne
from tables.numexpr.necompiler import (
    getContext, getExprNames, getType, NumExpr)
from tables.utilsExtension import lrange


shape = (1000,160000)
#shape = (10,1600)
filters = tb.Filters(complevel=1, complib="blosc", shuffle=0)
ofilters = tb.Filters(complevel=1, complib="blosc", shuffle=0)
#filters = tb.Filters(complevel=1, complib="lzo", shuffle=0)
#ofilters = tb.Filters(complevel=1, complib="lzo", shuffle=0)

# TODO: Makes it sense to add a 's'tring typecode here?
typecode_to_dtype = {'b': 'bool', 'i': 'int32', 'l': 'int64', 'f': 'float32',
                     'd': 'float64', 'c': 'complex128'}

def _compute(result, function, arguments,
             start=None, stop=None, step=None):
    """Compute the `function` over the `arguments` and put the outcome in `result`"""
    arg0 = arguments[0]
    if hasattr(arg0, 'maindim'):
        maindim = arg0.maindim
        (start, stop, step) = arg0._processRangeRead(start, stop, step)
        nrowsinbuf = arg0.nrowsinbuf
        print "nrowsinbuf-->", nrowsinbuf
    else:
        maindim = 0
        (start, stop, step) = (0, len(arg0), 1)
        nrowsinbuf = len(arg0)
    shape = list(arg0.shape)
    shape[maindim] = lrange(start, stop, step).length

    # The slices parameter for arg0.__getitem__
    slices = [slice(0, dim, 1) for dim in arg0.shape]

    # This is a hack to prevent doing unnecessary conversions
    # when copying buffers
    if hasattr(arg0, 'maindim'):
        for arg in arguments:
            arg._v_convert = False

    # Start the computation itself
    for start2 in lrange(start, stop, step*nrowsinbuf):
        # Save the records on disk
        stop2 = start2 + step * nrowsinbuf
        if stop2 > stop:
            stop2 = stop
        # Set the proper slice in the main dimension
        slices[maindim] = slice(start2, stop2, step)
        start3 = (start2-start)/step
        stop3 = start3 + nrowsinbuf
        if stop3 > shape[maindim]:
            stop3 = shape[maindim]
        # Compute the slice to be filled in destination
        sl = []
        for i in range(maindim):
            sl.append(slice(None,None,None))
        sl.append(slice(start3,stop3,None))
        # Get the values for computing the buffer
        values = [arg.__getitem__(tuple(slices)) for arg in arguments]
        result[tuple(sl)] = function(*values)

    # Activate the conversion again (default)
    if hasattr(arg0, 'maindim'):
        for arg in arguments:
            arg._v_convert = True

    return result


def evaluate(ex, out=None, local_dict=None, global_dict=None, **kwargs):
    """Evaluate expression and return an array."""

    # First, get the signature for the arrays in expression
    context = getContext(kwargs)
    names, _ = getExprNames(ex, context)

    # Get the arguments based on the names.
    call_frame = sys._getframe(1)
    if local_dict is None:
        local_dict = call_frame.f_locals
    if global_dict is None:
        global_dict = call_frame.f_globals
    arguments = []
    types = []
    for name in names:
        try:
            a = local_dict[name]
        except KeyError:
            a = global_dict[name]
        arguments.append(a)
        if hasattr(a, 'atom'):
            types.append(a.atom)
        else:
            types.append(a)

    # Create a signature
    signature = [(name, getType(type_)) for (name, type_) in zip(names, types)]
    print "signature-->", signature

    # Compile the expression
    compiled_ex = NumExpr(ex, signature, [], **kwargs)
    print "fullsig-->", compiled_ex.fullsig

    _compute(out, compiled_ex, arguments)

    return


if __name__=="__main__":
    iarrays = 0
    oarrays = 0
    doprofile = 1
    dokprofile = 0

    f = tb.openFile("/scratch2/faltet/evaluate.h5", "w")

    # Create some arrays
    if iarrays:
        a = np.ones(shape, dtype='float32')
        b = np.ones(shape, dtype='float32')*2
        c = np.ones(shape, dtype='float32')*3
    else:
        a = f.createCArray(f.root, 'a', tb.Float32Atom(dflt=1.),
                           shape=shape, filters=filters)
        a[:] = 1.
        b = f.createCArray(f.root, 'b', tb.Float32Atom(dflt=2.),
                           shape=shape, filters=filters)
        b[:] = 2.
        c = f.createCArray(f.root, 'c', tb.Float32Atom(dflt=3.),
                           shape=shape, filters=filters)
        c[:] = 3.
    if oarrays:
        out = np.empty(shape, dtype='float32')
    else:
        out = f.createCArray(f.root, 'out', tb.Float32Atom(),
                             shape=shape, filters=ofilters)

    t0 = time()
    if iarrays and oarrays:
        #out = ne.evaluate("a*b+c")
        out = a*b+c
    elif doprofile:
        import cProfile as prof
        import pstats
        prof.run('evaluate("a*b+c", out)', 'evaluate.prof')
        stats = pstats.Stats('evaluate.prof')
        stats.strip_dirs()
        stats.sort_stats('time', 'calls')
        stats.print_stats(20)
    elif dokprofile:
        from cProfile import Profile
        import lsprofcalltree
        prof = Profile()
        prof.run('evaluate("a*b+c", out)')
        kcg = lsprofcalltree.KCacheGrind(prof)
        ofile = open('evaluate.kcg','w')
        kcg.output(ofile)
        ofile.close()
    else:
        evaluate("a*b+c", out)
    print "Time for evaluate-->", round(time()-t0, 3)

    #print "out-->", `out`
    #print `out[:]`

    f.close()
