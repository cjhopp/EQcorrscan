#!/usr/bin/python
"""
Code to determine the birghtness function of seismic data according to a three-
dimensional travel-time grid.  This travel-time grid should be generated using
the grid2time function of the NonLinLoc package by Anthony Lomax which can be
found here: http://alomax.free.fr/nlloc/ and is not distributed within this
package as this is a very useful stand-alone library for seismic event location.

This code is based on the method of Frank & Shapiro 2014

Part of the EQcorrscan module to integrate seisan nordic files into a full
cross-channel correlation for detection routine.
EQcorrscan is a python module designed to run match filter routines for
seismology, within it are routines for integration to seisan and obspy.
With obspy integration (which is necessary) all main waveform formats can be
read in and output.

This main section contains a script, LFE_search.py which demonstrates the usage
of the built in functions from template generation from picked waveforms
through detection by match filter of continuous data to the generation of lag
times to be used for relative locations.

The match-filter routine described here was used a previous Matlab code for the
Chamberlain et al. 2014 G-cubed publication.  The basis for the lag-time
generation section is outlined in Hardebeck & Shelly 2011, GRL.

Code generated by Calum John Chamberlain of Victoria University of Wellington,
2015.

All rights reserved.

Pre-requisites:
    gcc             - for the installation of the openCV correlation routine
    python-joblib   - used for parallel processing
    python-obspy    - used for lots of common seismological processing
                    - requires:
                        numpy
                        scipy
                        matplotlib
    python-pylab    - used for plotting
    NonLinLoc       - used outside of all codes for travel-time generation
"""

def _read_tt(path, stations, phase):
    """
    Function to read in .csv files of slowness generated from Grid2Time (part
    of NonLinLoc by Anthony Lomax) and convert this to a useful format here.

    It should be noted that this can read either P or S travel-time grids, not
    both at the moment.

    :type path: str
    :param path: The path to the .csv Grid2Time outputs
    :type stations: list
    :param stations: List of station names to read slowness files for.

    :return: list stations, list of lists of tuples nodes, \
    :class: 'numpy.array' lags station[1] refers to nodes[1] and \
    lags[1] nodes[1][1] refers to station[1] and lags[1][1]\
    nodes[n][n] is a tuple of latitude, longitude and depth
    """

    import glob, sys, csv
    import numpy as np

    # Locate the slowness file information
    gridfiles=[]
    for station in stations:
        gridfiles+=(glob.glob(path+'/*.'+phase+'.'+station+'*.csv'))
    if not stations:
        print 'No slowness files found'
        sys.exit()
    # Read the files
    allnodes=[]
    for gridfile in gridfiles:
        print '     Reading slowness from: '+gridfile
        f=open(gridfile,'r')
        grid=csv.reader(f, delimiter=' ')
        traveltime=[]
        nodes=[]
        for row in grid:
            nodes.append((row[0],row[1],row[2]))
            traveltime.append(float(row[3]))
        traveltime=np.array(traveltime)
        lags=traveltime-min(traveltime)
        if not 'alllags' in locals():
            alllags=[lags]
        else:
            alllags=np.concatenate((alllags,[lags]), axis=0)
        allnodes=nodes  # each element of allnodes should be the same as the
                        # other one, e.g. for each station the grid must be the
                        # same, hence allnodes=nodes
        f.close()
    return stations, allnodes, alllags

def _resample_grid(stations, nodes, lags, volume, resolution):
    """
    Function to resample the lagtime grid to a given volume.  For use if the
    grid from Grid2Time is too large or you want to run a faster, downsampled
    scan.

    :type stations: list
    :param stations: List of station names from in the form where stations[i]\
    refers to nodes[i][:] and lags[i][:]
    :type nodes: list, tuple
    :param nodes: List of node points where nodes[i] referes to stations[i] and\
    nodes[:][:][0] is latitude in degrees, nodes[:][:][1] is longitude in\
    degrees, nodes[:][:][2] is depth in km.
    :type lags: :class: 'numpy.array'
    :param lags: Array of arrays where lags[i][:] refers to stations[i].\
    lags[i][j] should be the delay to the nodes[i][j] for stations[i] in seconds\
    :type volume: tuple
    :param volume: list of tuples: [(mindepth, maxdepth),(minlat, maxlat),(minlong,\
    maxlong)].  This will be interpreted as a cuboid.

    :return: list stations, list of lists of tuples nodes, :class: \
    'numpy.array' lags station[1] refers to nodes[1] and lags[1]\
    nodes[1][1] refers to station[1] and lags[1][1]\
    nodes[n][n] is a tuple of latitude, longitude and depth.
    """
    import sys, numpy as np
    resamp_nodes=[]
    resamp_lags=[]
    # Extract info from volume
    minlat=volume[0][0]
    maxlat=volume[0][1]
    minlong=volume[1][0]
    maxlong=volume[1][1]
    mindepth=volume[2][0]
    maxdepth=volume[2][1]
    # Check that the box makes sense
    if minlat >= maxlat or minlong >= maxlong or mindepth >= maxdepth:
        print "Your box doesn't make sense, check your values"
        sys.exit()
    # Cut the volume
    for i in xrange(0,len(nodes)):
        # If the node is within the range, keep it
        if minlong < float(nodes[i][0]) < maxlong and\
            minlat < float(nodes[i][1]) < maxlat and\
            mindepth < float(nodes[i][2]) < maxdepth:
                resamp_nodes.append(nodes[i])
                resamp_lags.append([lags[:,i]])
    # Reshape the lags
    resamp_lags=np.reshape(resamp_lags,(len(resamp_lags),len(stations))).T
    # Resample the nodes - they are sorted in order of size with largest long
    # then largest lat, then depth.

    return stations, resamp_nodes, resamp_lags

def _rm_similarlags(stations, nodes, lags, threshold):
    """
    Function to remove those nodes that have a very similar network moveout
    to another lag.

    Will, for each node, calculate the difference in lagtime at each station
    at every node, then sum these for each node to get a cumulative difference
    in network moveout.  This will result in an array of arrays with zeros on
    the diagonal.

    :type stations: list
    :param stations: List of station names from in the form where stations[i]\
    refers to nodes[i][:] and lags[i][:]
    :type nodes: list, tuple
    :param nodes: List of node points where nodes[i] referes to stations[i] and\
    nodes[:][:][0] is latitude in degrees, nodes[:][:][1] is longitude in\
    degrees, nodes[:][:][2] is depth in km.
    :type lags: :class: 'numpy.array'
    :param lags: Array of arrays where lags[i][:] refers to stations[i].\
    lags[i][j] should be the delay to the nodes[i][j] for stations[i] in seconds
    :type threhsold: float
    :param threshold: Threshold for removal in seconds

    :returns: list stations, list of lists of tuples nodes, :class: \
    'numpy.array' lags station[1] refers to nodes[1] and lags[1]\
    nodes[1][1] refers to station[1] and lags[1][1]\
    nodes[n][n] is a tuple of latitude, longitude and depth.
    """
    import numpy as np
    import sys
    netdif=abs((lags.T-lags.T[0]).sum(axis=1).reshape(1,len(nodes)))>threshold
    for i in xrange(len(nodes)):
        netdif=np.concatenate((netdif, \
                               abs((lags.T-lags.T[i]).sum(axis=1).reshape(1,len(nodes)))>threshold),\
                              axis=0)
        sys.stdout.write("\r"+str(float(i)/len(nodes)*100)+"% \r")
        sys.stdout.flush()
    nodes_out=[nodes[0]]
    node_indeces=[0]
    print "\n"
    print len(nodes)
    for i in xrange(1,len(nodes)):
        if np.all(netdif[i][node_indeces]):
            node_indeces.append(i)
            nodes_out.append(nodes[i])
    lags_out=lags.T[node_indeces].T
    print "Removed "+str(len(nodes)-len(nodes_out))+" duplicate nodes"
    return stations, nodes_out, lags_out


def _node_loop(stations, node, lags, stream):
    """
    Internal function to allow for parallelisation of brightness

    :type stations: list
    :type node: tuple
    :type lags: list
    :type stream: :class: `obspy.Stream`

    :return: energy (np.array), node (tuple), realstations (list of stations actaully used)
    """
    import numpy as np
    i=0
    # Print what node we are working on as a check that things are happening!
    print 'Running the brightness function for: '+str(node)
    # Loop through stations
    for station in stations:
        st=stream.select(station=station)
        lag=lags[i]
        # Loop through channels
        if st:
            for tr in st:
                lagged_data=tr.data[int(lag*tr.stats.sampling_rate):]
                pad=np.zeros(int(lag*tr.stats.sampling_rate))
                lagged_energy=np.square(np.concatenate((pad,lagged_data)))
                if not 'energy' in locals():
                    energy=(lagged_energy/np.sqrt(np.mean(np.square(lagged_energy)))).reshape(1,len(lagged_energy))
                else:
                    # Apply lag to data and add it to energy - normalize the data here
                    energy=np.concatenate((energy,(lagged_energy/np.sqrt(np.mean(np.square(lagged_energy)))).reshape(1,len(lagged_energy))), axis=0)
                    energy=np.sum(energy, axis=0).reshape(1,len(lagged_energy))
    return energy

def _find_detections(cum_net_resp, nodes, threshold, thresh_type, samp_rate, realstations):
    """
    Function to find detections within the cumulative network response according
    to Frank et al. (2014).

    :type cum_net_resp: np.array
    :param cum_net_resp: Array of cumulative network response for nodes
    :type nodes: list of tuples
    :param nodes: Nodes associated with the source of energy in the cum_net_resp
    :type threshold: float
    :type thresh_type: str
    :type samp_rate: float
    :type realstations: list of str

    :return: detections as class DETECTION
    """
    from utils import findpeaks
    from par import template_gen_par as defaults
    from core.match_filter import DETECTION
    import numpy as np

    if thresh_type=='MAD':
        thresh=(np.median(np.abs(cum_net_resp))*threshold) # Raise to the power
    elif thresh_type=='abs':
        thresh=threshold
    print 'Threshold is set to: '+str(thresh)
    print 'Max of data is: '+str(max(cum_net_resp))
    peaks=findpeaks.find_peaks2(cum_net_resp, thresh,
                    defaults.length*samp_rate, debug=0)
    detections=[]
    if peaks:
        for peak in peaks:
            node=nodes[peak[1]]
            detections.append(DETECTION(node[0]+'_'+node[1]+'_'+node[2],
                                         peak[1]/samp_rate,
                                         len(realstations), peak[0], thresh,
                                         'brightness', realstations))
    else:
        detections=[]
    print 'I have found '+str(len(peaks))+' possible detections'
    return detections

def coherance(stream):
    """
    Function to determine the average network coherance of a given template or
    detection.  You will want your stream to contain only signal as noise
    will reduce the coherance (assuming it is incoherant random noise).

    :type stream: obspy.Stream
    :param stream: The stream of seismic data you want to calculate the
                    coherance for.

    :return: float - coherance
    """
    import numpy as np
    coherance=0.0
    from match_filter import normxcorr2
    # Loop through channels and generate a correlation value for each
    # unique cross-channel pairing
    for i in xrange(len(stream)):
        for j in xrange(i+1,len(stream)):
            coherance+=np.abs(normxcorr2(stream[i].data, stream[j].data))
    coherance=coherance/len(stream)
    return coherance

def brightness(stations, nodes, lags, stream, threshold, thresh_type,
        coherance_thresh):
    """
    Function to calculate the brightness function in terms of energy for a day
    of data over the entire network for a given grid of nodes.

    Note data in stream must be all of the same length and have the same
    sampling rates.

    :type stations: list
    :param stations: List of station names from in the form where stations[i]\
    refers to nodes[i][:] and lags[i][:]
    :type nodes: list, tuple
    :param nodes: List of node points where nodes[i] referes to stations[i] and\
    nodes[:][:][0] is latitude in degrees, nodes[:][:][1] is longitude in\
    degrees, nodes[:][:][2] is depth in km.
    :type lags: :class: 'numpy.array'
    :param lags: Array of arrays where lags[i][:] refers to stations[i].\
    lags[i][j] should be the delay to the nodes[i][j] for stations[i] in seconds.
    :type stream: :class: `obspy.Stream`
    :param data: Data through which to look for detections.
    :type threshold: float
    :param threshold: Threshold value for detection of template within the\
    brightness function
    :type thresh_type: str
    :param thresh_type: Either MAD or abs where MAD is the Mean Absolute\
    Deviation and abs is an absoulte brightness.
    :type coherance_thresh: float
    :param coherance_thresh: Threshold for removing incoherant peaks in the\
            network response, those below this will not be used as templates.

    :return: list of templates as :class: `obspy.Stream` objects
    """
    from core.template_gen import _template_gen
    from par import template_gen_par as defaults
    from joblib import Parallel, delayed
    from utils.Sfile_util import PICK
    import sys
    from copy import deepcopy
    from obspy import read as obsread
    import numpy as np
    # Check that we actually have the correct stations
    realstations=[]
    for station in stations:
        st=stream.select(station=station)
        if st:
            realstations+=station
    energy=np.array([np.array([np.nan]*len(stream[0]))]*len(nodes))
    detections=[]
    detect_lags=[]
    parallel=False
    # Loop through each node in the input
    # Linear run
    if not parallel:
        for i in xrange(0,len(nodes)):
            energy[i]=_node_loop(stations, nodes[i], lags[:,i],
                                  stream)
    else:
        # Parallel run
        energy[i]=Parallel(n_jobs=2, verbose=5)(delayed(_node_loop)(stations, nodes[i],
                                                          lags[:,i], stream)\
                                                          for i in xrange(0,len(nodes)))
    # Now compute the cumulative network response and then detect possible events
    indeces=np.argmax(energy, axis=0) # Indeces of maximum energy
    cum_net_resp=np.array([np.nan]*len(indeces))
    cum_net_resp[0]=energy[indeces[0]][0]
    peak_nodes=[nodes[indeces[0]]]
    for i in xrange(1, len(indeces)):
        cum_net_resp[i]=energy[indeces[i]][i]
        peak_nodes.append(nodes[indeces[i]])
    del energy, indeces
    # Plot the data - convert cum_net_resp to a seismic Trace for simple plotting
    # tr_net_resp=deepcopy(st[0])
    # tr_net_resp.data=cum_net_resp
    # tr_net_resp.plot()
    # Find detection within this network response
    print 'Finding detections in the cumulatve network response'
    detections=_find_detections(cum_net_resp, peak_nodes, threshold, thresh_type,\
                     stream[0].stats.sampling_rate, realstations)
    del cum_net_resp
    templates=[]
    # temp_det=[]
    # return detections
    # print np.shape(detections)
    # for detection in detections: # Flatten list
        # temp_det=temp_det+detection
    # detections=temp_det
    j=0
    if detections:
        print 'Converting detections in to templates'
        for detection in detections:
            print 'Converting for detection '+str(j)+' of '+str(len(detections))
            j+=1
            copy_of_stream=deepcopy(stream)
            # Convert detections to PICK type - name of detection template
            # is the node.
            node=(detection.template_name.split('_')[0],\
                    detection.template_name.split('_')[1],\
                    detection.template_name.split('_')[2])
            # Look up node in nodes and find the associated lags
            index=peak_nodes.index(node)
            detect_lags=lags[:,index]
            i=0
            picks=[]
            for detect_lag in detect_lags:
                station=stations[i]
                st=copy_of_stream.select(station=station)
                if len(st) != 0:
                    for tr in st:
                        #print tr.stats.station+'.'+tr.stats.channel+' at lag '+\
                        #    str(detect_lag)+' at time '+str(detection.detect_time)+\
                        #   ' on day '+str(tr.stats.starttime)
                        # if len(tr.stats.channel) != 3:
                            # print 'There is no channel for for this pick!!!'
                            # print station+' pick number: '+str(j)
                            # print tr.stats.starttime+detect_lag+detection.detect_time
                            # st.plot()
                            # sys.exit()
                        picks.append(PICK(station=station,
                                          channel=tr.stats.channel,
                                          impulsivity='E', phase='S',
                                          weight='3', polarity='',
                                          time=tr.stats.starttime+detect_lag+detection.detect_time,
                                          coda='', amplitude='', peri='',
                                          azimuth='', velocity='', AIN='', SNR='',
                                          azimuthres='', timeres='',
                                          finalweight='', distance='',
                                          CAZ=''))
                i+=1
            print 'Generating template for detection: '+str(j)
            template=(_template_gen(picks, copy_of_stream, defaults.length, 'all'))
            template_name=defaults.saveloc+'/'+\
                    str(template[0].stats.starttime)+'.ms'
                # In the interests of RAM conservation we write then read
            # Check coherancy here!
            if coherance(template) > coherance:
                template.write(template_name,format="MSEED")
                print 'Written template as: '+template_name
                coherant=True
            else:
                print 'Template was incoherant'
                coherant=False
            del copy_of_stream, tr, template
            if coherant:
                templates.append(obsread(template_name))
        else:
            print 'No templates for you'
    return templates

