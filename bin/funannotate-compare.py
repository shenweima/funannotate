#!/usr/bin/env python
from __future__ import division

import sys, os, subprocess, inspect, multiprocessing, shutil, argparse, re
from datetime import datetime
from goatools import obo_parser
from Bio import SeqIO
from natsort import natsorted
import pandas as pd
import numpy as np

currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0,parentdir)
import lib.library as lib

#setup menu with argparse
class MyFormatter(argparse.ArgumentDefaultsHelpFormatter):
    def __init__(self,prog):
        super(MyFormatter,self).__init__(prog,max_help_position=48)
parser=argparse.ArgumentParser(prog='funannotate-compare.py', usage="%(prog)s [options] genome1.gbk genome2.gbk",
    description='''Funannotate comparative genomics.''',
    epilog="""Written by Jon Palmer (2015) nextgenusfs@gmail.com""",
    formatter_class = MyFormatter)
parser.add_argument('-i','--input', nargs='+', help='List of funannotate genome folders')
parser.add_argument('-o','--out', default='funannotate_compare', help='Name of output folder')
parser.add_argument('--cpus', default=2, type=int, help='Number of CPUs to utilize')
parser.add_argument('--go_fdr', default=0.05, type=float, help='P-value for FDR GO-enrichment')
parser.add_argument('--heatmap_stdev', default=1.0, type=float, help='Standard Deviation threshold for heatmap retention')
parser.add_argument('--bootstrap', default=100, type=int, help='Number of bootstraps to run with RAxML')
parser.add_argument('--num_orthos', default=500, type=int, help='Number of Single-copy orthologs to run with RAxML')
parser.add_argument('--outgroup', help='Name of species for RAxML outgroup')
args=parser.parse_args()
            

#make output folder
if not os.path.isdir(args.out):
    os.makedirs(args.out)
go_folder = os.path.join(args.out, 'go_terms')
protortho = os.path.join(args.out, 'protortho')
phylogeny = os.path.join(args.out, 'phylogeny')
if os.path.isdir(go_folder):
    shutil.rmtree(go_folder)
    os.makedirs(go_folder)
else:
    os.makedirs(go_folder)
if not os.path.isdir(protortho):
    os.makedirs(protortho)
if not os.path.isdir(phylogeny):
    os.makedirs(phylogeny)

#create log file
log_name = os.path.join(args.out, 'funnannotate-compare.log')
if os.path.isfile(log_name):
    os.remove(log_name)

#initialize script, log system info and cmd issue at runtime
lib.setupLogging(log_name)
FNULL = open(os.devnull, 'w')
cmd_args = " ".join(sys.argv)+'\n'
lib.log.debug(cmd_args)
print "-------------------------------------------------------"
lib.log.info("Operating system: %s, %i cores, ~ %i GB RAM" % (sys.platform, multiprocessing.cpu_count(), lib.MemoryCheck()))

#get version of funannotate
version = lib.get_version()
lib.log.info("Running %s" % version)

if args.outgroup:
    if not os.path.isdir(os.path.join(parentdir, 'DB', 'outgroups')):
        lib.log.error("Outgroup folder is not properly configured")
        os._exit(1)
    files = [f for f in os.listdir(os.path.join(parentdir, 'DB', 'outgroups'))]
    files = [ x.replace('_buscos.fa', '') for x in files ]
    files = [ x for x in files if not x.startswith('.') ]
    if not args.outgroup in files:
        lib.log.error("%s is not found in outgroups" % args.outgroup)
        print natsorted(files)
    else:
        outgroup = True
        outgroup_species = os.path.join(parentdir, 'DB', 'outgroups', args.outgroup+'_buscos.fa')
        outgroup_name = args.outgroup
else:
    outgroup = False
    outgroup_species = ''
    outgroup_name = ''


#check dependencies and set path to proteinortho
#PROTORTHO = os.path.join(parentdir, 'util', 'proteinortho_v5.11', 'proteinortho5.pl')
programs = ['find_enrichment.py', 'mafft', 'raxmlHPC-PTHREADS', 'trimal', 'proteinortho5.pl']
lib.CheckDependencies(programs)

#copy over html files
if not os.path.isdir(os.path.join(args.out,'css')):
    lib.copyDirectory(os.path.join(parentdir, 'html_template', 'css'), os.path.join(args.out, 'css'))
if not os.path.isdir(os.path.join(args.out, 'js')):
    lib.copyDirectory(os.path.join(parentdir, 'html_template', 'js'), os.path.join(args.out, 'js'))

#loop through each genome
stats = []
merops = []
ipr = []
cazy = []
pfam = []
eggnog = []
busco = []
gbkfilenames = []
scinames = []
num_input = len(args.input)
if num_input == 0:
    lib.log.error("Error, you did not specify an input, -i")
    os._exit(1)
lib.log.info("Now parsing %i genomes" % num_input)
for i in range(0,num_input):
    #parse the input, I want user to give output folder for funannotate, put they might give a results folder, so do the best you can to check
    if not os.path.isdir(args.input[i]):
        lib.log.error("Error, one of the inputs is not a folder")
        os._exit(1)
    else: #split arguments into genomes and run a bunch of stats/comparisons
        #look for annotate_results folder
        GBK = ''
        fun_dir = args.input[i]
        if not os.path.isdir(os.path.join(args.input[i], 'annotate_results')): #this means was not passed the whole folder
            fun_dir = lib.get_parent_dir(args.input[i]) #set fun_dir up a directory to find other results if needed
            for file in os.listdir(args.input[i]):
                if file.endswith('.gbk'):
                    GBK = os.path.join(args.input[i], file) 
        else: #whole folder is passed, now get the genbank file
            for file in os.listdir(os.path.join(args.input[i], 'annotate_results')):
                if file.endswith('.gbk'):
                    GBK = os.path.join(args.input[i], 'annotate_results', file)
        if not GBK: #check this
            lib.log.error("Error, was not able to find appropriate GenBank file in the annotate_results folder")
        gbkfilenames.append(GBK)
        #now run genome routines
        stats.append(lib.genomeStats(GBK))
        merops.append(lib.getStatsfromNote(GBK, 'MEROPS'))
        ipr.append(lib.getStatsfromDbxref(GBK, 'InterPro'))
        pfam.append(lib.getStatsfromDbxref(GBK, 'PFAM'))
        cazy.append(lib.getStatsfromNote(GBK, 'CAZy'))
        busco.append(lib.getStatsfromNote(GBK, 'BUSCO'))
        lib.parseGOterms(GBK, go_folder, stats[i][0].replace(' ', '_'))
        lib.gb2proteinortho(GBK, protortho, stats[i][0].replace(' ', '_'))
        eggnog.append(lib.getEggNogfromNote(GBK))
        scinames.append(stats[i][0].replace(' ', '_'))

#convert busco to dictionary
busco = lib.busco_dictFlip(busco)

#add species names to pandas table
names = []
for i in stats:
    sci_name = i[0]
    if '_' in sci_name: #here I'm assuming that somebody used an abbreviated name and an underscore, this would be atypical I think
        names.append(sci_name)
    else:
        genus = sci_name.split(' ')[0]
        species = ' '.join(sci_name.split(' ')[1:])
        abbrev = genus[:1] + '.'
        final_name = abbrev + ' ' + species
        names.append(final_name)


#PFAM#############################################
lib.log.info("Summarizing PFAM domain results")
if not os.path.isdir(os.path.join(args.out, 'pfam')):
    os.makedirs(os.path.join(args.out, 'pfam'))

#convert to counts
pfamdf = lib.convert2counts(pfam)
pfamdf.fillna(0, inplace=True)
pfamdf['species'] = names
pfamdf.set_index('species', inplace=True)

#remove any "empty" genomes
pfamdf = pfamdf[(pfamdf.T != 0).any()]

#make an nmds
if len(pfamdf.index) > 1: #make sure number of species is at least two
    lib.distance2mds(pfamdf, 'braycurtis', 'PFAM', os.path.join(args.out, 'pfam','PFAM.nmds.pdf'))

#get the PFAM descriptions
pfamdf2 = pfamdf.transpose()
PFAM = lib.pfam2dict(os.path.join(parentdir, 'DB', 'Pfam-A.clans.tsv'))
pfam_desc = []
for i in pfamdf2.index.values:
    pfam_desc.append(PFAM.get(i))
pfamdf2['descriptions'] = pfam_desc
#write to file
pfamdf2.to_csv(os.path.join(args.out, 'pfam', 'pfam.results.csv'))
pfamdf2.reset_index(inplace=True)
pfamdf2.rename(columns = {'index':'PFAM'}, inplace=True)
pfamdf2['PFAM'] = '<a href="http://pfam.xfam.org/family/'+ pfamdf2['PFAM'].astype(str)+'">'+pfamdf2['PFAM']+'</a>'
#create html output
with open(os.path.join(args.out, 'pfam.html'), 'w') as output:
    pd.set_option('display.max_colwidth', -1)
    output.write(lib.HEADER)
    output.write(lib.PFAM)
    output.write(pfamdf2.to_html(index=False, escape=False, classes='table table-hover'))
    output.write(lib.FOOTER)

##################################################

####InterProScan##################################
lib.log.info("Summarizing InterProScan results")
if not os.path.isdir(os.path.join(args.out, 'interpro')):
    os.makedirs(os.path.join(args.out, 'interpro'))

#convert to counts
IPRdf = lib.convert2counts(ipr)
IPRdf.fillna(0, inplace=True) #fill in zeros for missing data
IPRdf['species'] = names
IPRdf.set_index('species', inplace=True)

#some checking here of data, if genome is missing, i.e. counts are zero, drop it
#print IPRdf
#print len(IPRdf.columns)
IPRdf = IPRdf[(IPRdf.T != 0).any()]
#print len(IPRdf.index)

#analysis of InterPro Domains
#get IPR descriptions
lib.log.info("Loading InterPro descriptions")
INTERPRO = lib.iprxml2dict(os.path.join(parentdir, 'DB', 'interpro.xml'))
#NMDS
if len(IPRdf.index) > 1: #count number of species
    if len(IPRdf.columns) > 1: #count number of IPR domains
        lib.distance2mds(IPRdf, 'braycurtis', 'InterProScan', os.path.join(args.out, 'interpro', 'InterProScan.nmds.pdf'))
    
        #write to csv file
        ipr2 = IPRdf.transpose()
        ipr_desc = []
        for i in ipr2.index.values:
            ipr_desc.append(INTERPRO.get(i))
        ipr2['descriptions'] = ipr_desc
        ipr2.to_csv(os.path.join(args.out, 'interpro','interproscan.results.csv'))
        ipr2.reset_index(inplace=True)
        ipr2.rename(columns = {'index':'InterPro'}, inplace=True)
        ipr2['InterPro'] = '<a href="http://www.ebi.ac.uk/interpro/entry/'+ ipr2['InterPro'].astype(str)+'">'+ipr2['InterPro']+'</a>'

#create html output
with open(os.path.join(args.out, 'interpro.html'), 'w') as output:
    pd.set_option('display.max_colwidth', -1)
    output.write(lib.HEADER)
    output.write(lib.INTERPRO)
    if len(IPRdf.columns) > 1:
        if len(IPRdf.index) > 1:
            output.write(ipr2.to_html(index=False, escape=False, classes='table table-hover'))
    output.write(lib.FOOTER)

##############################################

####MEROPS################################
lib.log.info("Summarizing MEROPS protease results")
if not os.path.isdir(os.path.join(args.out, 'merops')):
    os.makedirs(os.path.join(args.out, 'merops'))

MEROPS = {'A': 'Aspartic Peptidase', 'C': 'Cysteine Peptidase', 'G': 'Glutamic Peptidase', 'M': 'Metallo Peptidase', 'N': 'Asparagine Peptide Lyase', 'P': 'Mixed Peptidase','S': 'Serine Peptidase', 'T': 'Threonine Peptidase', 'U': 'Unknown Peptidase'}
#convert to counts
meropsdf = lib.convert2counts(merops)
meropsdf.fillna(0, inplace=True)
meropsdf['species'] = names
meropsdf.set_index('species', inplace=True)

#make a simple table with just these numbers
meropsA = meropsdf.filter(regex='A').sum(numeric_only=True, axis=1)
meropsC = meropsdf.filter(regex='C').sum(numeric_only=True, axis=1)
meropsG = meropsdf.filter(regex='G').sum(numeric_only=True, axis=1)
meropsM = meropsdf.filter(regex='M').sum(numeric_only=True, axis=1)
meropsN = meropsdf.filter(regex='N').sum(numeric_only=True, axis=1)
meropsP = meropsdf.filter(regex='P').sum(numeric_only=True, axis=1)
meropsS = meropsdf.filter(regex='S').sum(numeric_only=True, axis=1)
meropsT = meropsdf.filter(regex='T').sum(numeric_only=True, axis=1)
meropsU = meropsdf.filter(regex='U').sum(numeric_only=True, axis=1)
#get totals for determining height of y-axis
totals = meropsdf.sum(numeric_only=True, axis=1)
max_num = max(totals)
round_max = int(lib.roundup(max_num))
diff = round_max - int(max_num)
if diff < 100:
    ymax = round_max + 100
else:
    ymax = round_max
if round_max == 100 and diff > 50:
    ymax = max_num + 10
#recombine sums
enzymes = ['A', 'C', 'G', 'M', 'N', 'P', 'S', 'T', 'U']
meropsShort = pd.concat([meropsA, meropsC, meropsG, meropsM, meropsN, meropsP, meropsS, meropsT, meropsU], axis=1, keys=enzymes)
meropsShort['species'] = names
meropsShort.set_index('species', inplace=True)
#remove any columns with no hits
meropsShort = meropsShort.loc[:, (meropsShort != 0).any(axis=0)]
meropsall = meropsdf.transpose()

#write to file
meropsdf.transpose().to_csv(os.path.join(args.out, 'merops', 'MEROPS.all.results.csv'))
meropsShort.transpose().to_csv(os.path.join(args.out, 'merops', 'MEROPS.summary.results.csv'))

#draw plots for merops data
#stackedbar graph
if len(args.input) > 1:
    lib.drawStackedBar(meropsShort, 'MEROPS', MEROPS, ymax, os.path.join(args.out, 'merops', 'MEROPS.graph.pdf'))

#drawheatmap of all merops families where there are any differences 
if len(args.input) > 1:
    stdev = meropsall.std(axis=1)
    meropsall['stdev'] = stdev
    if len(meropsall) > 25:
        df2 = meropsall[meropsall.stdev >= args.heatmap_stdev ]
        lib.log.info("found %i/%i MEROPS familes with stdev >= %f" % (len(df2), len(meropsall), args.heatmap_stdev))
    else:
        df2 = meropsall
        lib.log.info("found %i MEROPS familes" % (len(df2)))
    meropsplot = df2.drop('stdev', axis=1)
    if len(meropsplot) > 0:
        lib.drawHeatmap(meropsplot, 'BuPu', os.path.join(args.out, 'merops', 'MEROPS.heatmap.pdf'), False)

    meropsall.reset_index(inplace=True)
    meropsall.rename(columns = {'index':'MEROPS'}, inplace=True)
    meropsall['MEROPS'] = '<a href="https://merops.sanger.ac.uk/cgi-bin/famsum?family='+ meropsall['MEROPS'].astype(str)+'">'+meropsall['MEROPS']+'</a>'

#create html output
with open(os.path.join(args.out, 'merops.html'), 'w') as output:
    pd.set_option('display.max_colwidth', -1)
    output.write(lib.HEADER)
    output.write(lib.MEROPS)
    output.write(meropsall.to_html(escape=False, index=False, classes='table table-hover'))
    output.write(lib.FOOTER)

#######################################################

#####run CAZy routine#################################
lib.log.info("Summarizing CAZyme results")
if not os.path.isdir(os.path.join(args.out, 'cazy')):
    os.makedirs(os.path.join(args.out, 'cazy'))
#convert to counts
CAZydf = lib.convert2counts(cazy)

#with CAZy there are 7 possible families
CAZY = {'CBM': 'Carbohydrate-binding module', 'CE': 'Carbohydrate esterase','GH': 'Glycoside hydrolase', 'GT': 'Glycosyltransferase', 'PL': 'Polysaccharide lyase', 'AA': 'Auxillary activities'}
#make a simple table with just these numbers
cazyAA = CAZydf.filter(regex='AA').sum(numeric_only=True, axis=1)
cazyGT = CAZydf.filter(regex='GT').sum(numeric_only=True, axis=1)
cazyPL = CAZydf.filter(regex='PL').sum(numeric_only=True, axis=1)
cazyCE = CAZydf.filter(regex='CE').sum(numeric_only=True, axis=1)
cazyCBM = CAZydf.filter(regex='CBM').sum(numeric_only=True, axis=1)
cazyGH = CAZydf.filter(regex='GH').sum(numeric_only=True, axis=1)
#get totals for determining height of y-axis
totals = CAZydf.sum(numeric_only=True, axis=1)
max_num = max(totals)
round_max = int(lib.roundup(max_num))
diff = round_max - int(max_num)
if diff < 100:
    ymax = round_max + 100
else:
    ymax = round_max
if round_max == 100 and diff > 50:
    ymax = max_num + 10
#print max_num, round_max, diff, ymax
enzymes = ['AA', 'CBM', 'CE', 'GH', 'GT', 'PL']
CAZyShort = pd.concat([cazyAA, cazyCBM, cazyCE, cazyGH, cazyGT, cazyPL], axis=1, keys=enzymes)
CAZydf['species'] = names
CAZyShort['species'] = names
CAZydf.set_index('species', inplace=True)
CAZyShort.set_index('species', inplace=True)
cazyall = CAZydf.transpose()

#write to file
CAZydf.transpose().to_csv(os.path.join(args.out, 'cazy', 'CAZyme.all.results.csv'))
CAZyShort.transpose().to_csv(os.path.join(args.out, 'cazy', 'CAZyme.summary.results.csv'))

#draw stacked bar graph for CAZY's
if len(args.input) > 1:
    lib.drawStackedBar(CAZyShort, 'CAZyme', CAZY, ymax, os.path.join(args.out, 'cazy', 'CAZy.graph.pdf'))

#if num of cazys greater than 25, drawheatmap of all CAZys that have standard deviation > X
if len(args.input) > 1:
    stdev = cazyall.std(axis=1)
    cazyall['stdev'] = stdev
    if len(cazyall) > 25:
        df2 = cazyall[cazyall.stdev >= args.heatmap_stdev ]
        lib.log.info("found %i/%i CAZy familes with stdev >= %f" % (len(df2), len(cazyall), args.heatmap_stdev))
    else:
        df2 = cazyall
        lib.log.info("found %i CAZy familes" % (len(df2)))
    cazyplot = df2.drop('stdev', axis=1)
    if len(cazyplot) > 0:
        lib.drawHeatmap(cazyplot, 'YlOrRd', os.path.join(args.out, 'cazy', 'CAZy.heatmap.pdf'), False)

    cazyall.reset_index(inplace=True)
    cazyall.rename(columns = {'index':'CAZy'}, inplace=True)
    cazyall['CAZy'] = '<a href="http://www.cazy.org/'+ cazyall['CAZy'].astype(str)+'.html">'+cazyall['CAZy']+'</a>'

#create html output
with open(os.path.join(args.out, 'cazy.html'), 'w') as output:
    pd.set_option('display.max_colwidth', -1)
    output.write(lib.HEADER)
    output.write(lib.CAZY)
    output.write(cazyall.to_html(escape=False, index=False, classes='table table-hover'))
    output.write(lib.FOOTER)
########################################################

####GO Terms, GO enrichment############################
if not os.path.isdir(os.path.join(args.out, 'go_enrichment')):
    os.makedirs(os.path.join(args.out, 'go_enrichment'))

if len(args.input) > 1:
    #concatenate all genomes into a population file
    lib.log.info("Running GO enrichment for each genome")
    with open(os.path.join(go_folder, 'population.txt'), 'w') as pop:
        for file in os.listdir(go_folder):
            if not file.startswith('associations'):
                file = os.path.join(go_folder, file)
                with open(file) as input:
                    pop.write(input.read())

    #now loop through each genome comparing to population
    for f in os.listdir(go_folder):
        if f.startswith('associations'):
            continue
        if f.startswith('population'):
            continue
        file = os.path.join(go_folder, f)
        base = f.replace('.txt', '')
        goa_out = os.path.join(args.out, 'go_enrichment', base+'.go.enrichment.txt')
        with open(goa_out, 'w') as output:
            subprocess.call(['find_enrichment.py', '--obo', os.path.join(parentdir, 'DB', 'go.obo'), '--pval', '0.001', '--alpha', '0.001', '--method', 'fdr', file, os.path.join(go_folder, 'population.txt'), os.path.join(go_folder, 'associations.txt')], stderr=FNULL, stdout=output)

    #load into pandas and write to html
    with open(os.path.join(args.out, 'go.html'), 'w') as output:
        pd.set_option('display.max_colwidth', -1)
        pd.options.mode.chained_assignment = None #turn off warning
        output.write(lib.HEADER)
        output.write(lib.GO)
        for f in os.listdir(os.path.join(args.out, 'go_enrichment')):
            if f.endswith('go.enrichment.txt'):
                file = os.path.join(args.out, 'go_enrichment', f)
                base = file.split('.go_enrichment.txt')[0]
                name = base.split('/')[-1]
                #check output, > 3 lines means there is some data, otherwise nothing.
                num_lines = sum(1 for line in open(file))
                output.write('<h4 class="sub-header" align="left">GO Enrichment: '+name+'</h4>')
                if num_lines > 9: #goatools changed output, empty files now have 9 lines instead of 3...
                    df = pd.read_csv(file, sep='\t', skiprows=8) #the 9th row is the header
                    df['enrichment'].replace('p', 'under', inplace=True)
                    df['enrichment'].replace('e', 'over', inplace=True)
                    df2 = df.loc[df['p_fdr'] < args.go_fdr]
                    df2.sort_values(by='enrichment', inplace=True)
                    if len(df2) > 0:
                        df2.to_csv(base+'.fdr_enriched.csv', index=False)
                        #apparently goatools also changed the headers....arrggh...
                        df2['GO'] = '<a href="http://amigo.geneontology.org/amigo/search/ontology?q='+ df2['GO'].astype(str)+'">'+df2['GO']+'</a>'
                        output.write(df2.to_html(escape=False, index=False, classes='table table-hover'))
                    else:
                        output.write('<table border="1" class="dataframe table table-hover">\n<th>No enrichment found</th></table>')
                else:
                    output.write('<table border="1" class="dataframe table table-hover">\n<th>No enrichment found</th></table>')
        output.write(lib.FOOTER)
    
#################################################### 

##ProteinOrtho################################
if not os.path.isdir(os.path.join(args.out, 'annotations')):
    os.makedirs(os.path.join(args.out, 'annotations'))
scoCount = 0
if len(args.input) > 1:
    lib.log.info("Running orthologous clustering tool, ProteinOrtho5.  This may take awhile...")
    #setup protein ortho inputs, some are a bit strange in the sense that they use equals signs
    log = os.path.join(protortho, 'proteinortho.log')
    
    #generate list of files based on input order for consistency
    filelist = []
    for i in stats:
        name = i[0].replace(' ', '_')
        name = name+'.faa'
        filelist.append(name)
    fileinput = ' '.join(filelist)
    #print fileinput
    cmd = ['proteinortho5.pl', '-project=funannotate', '-synteny', '-cpus='+str(args.cpus), '-singles', '-selfblast']
    cmd2 = cmd + filelist
    if not os.path.isfile(os.path.join(args.out, 'protortho', 'funannotate.poff')):
        with open(log, 'w') as logfile:
            subprocess.call(cmd2, cwd = protortho, stderr = logfile, stdout = logfile)

    #open poff in pandas to parse "easier" for stats, orthologs, etc
    df = pd.read_csv(os.path.join(args.out, 'protortho', 'funannotate.poff'), sep='\t', header=0)
    df.rename(columns=lambda x: x.replace('.faa', ''), inplace=True)
    #reorder table to it matches up with busco list of dicts
    newhead = [df.columns.values[0], df.columns.values[1], df.columns.values[2]]
    newhead += scinames
    df = df[newhead]
    #write to file (not sure I need this now?)
    #df.to_csv(os.path.join(args.out, 'protortho', 'funannotate_reorder.poff'), sep='\t', index=False)
    #now filter table to only single copy orthologs to use with phylogeny       
    num_species = len(df.columns) - 3
    sco = df[(df['# Species'] == num_species) & (df['Genes'] == num_species)]
    sco_hits = sco.drop(sco.columns[0:3], axis=1)
    #now cross reference with busco, as we want this for phylogeny
    keep = []
    sc_buscos = []
    for index, row in sco_hits.iterrows():
        busco_check = []
        for i in range(0, num_species):
            if row[i] in busco[i]:
                busco_check.append(busco[i].get(row[i]))
        busco_check = lib.flatten(busco_check)
        #need to check if outgroup is passed and this model exists in that outgroup         
        if len(set(busco_check)) == 1:
            if args.outgroup:
                available_busco = []
                with open(outgroup_species, 'rU') as outfasta:
                    for line in outfasta:
                        if line.startswith('>'):
                            line = line.replace('\n', '')
                            name = line.replace('>', '')
                            available_busco.append(name)
                if busco_check[0] in available_busco:
                    keep.append(index)
                    sc_buscos.append(busco_check[0])
            else:
                keep.append(index)
    sco_final = sco_hits.ix[keep]     
    
    #take dataframe and output the ortholog table.
    dftrim = df.drop(df.columns[0:3], axis=1)  #trim down to just gene models
    orthdf = df[(df['# Species'] > 1)]  #get rid of singletons in this dataset
    orth_hits = orthdf.drop(orthdf.columns[0:3], axis=1) #trim to just gene models
    
    orthologs = os.path.join(args.out, 'annotations','orthology_groups.txt')
    with open(orthologs, 'w') as output:
        #should be able to parse the pandas ortho dataframe now
        for index, row in orth_hits.iterrows():
            ID = 'orth'+str(index)
            buscos = []
            eggs = []
            proteins = []
            for x in range(0, len(row)):
                if row[x] != '*':
                    prots = row[x].split(',')
                    for y in prots:
                        proteins.append(y)
                        egghit = eggnog[x].get(y)
                        if not egghit in eggs:
                            eggs.append(egghit)
                        buscohit = busco[x].get(y)
                        if not buscohit in buscos:
                            buscos.append(buscohit)
            #clean up the None's that get added
            eggs = [x for x in eggs if x is not None]
            buscos = [x for x in buscos if x is not None]
            buscos = lib.flatten(buscos)
            
            #write to output
            if len(eggs) > 0:
                eggs = ', '.join(str(v) for v in eggs)
            else:
                eggs = 'None'
            if len(buscos) > 0:
                buscos = set(buscos)
                buscos = ', '.join(str(v) for v in buscos)
            else:
                buscos = 'None'
            output.write("%s\t%s\t%s\t%s\n" % (ID, eggs, buscos, ', '.join(proteins)))

if not os.path.isdir(os.path.join(args.out, 'stats')):
    os.makedirs(os.path.join(args.out, 'stats'))
summary = []
#get stats, this is all single copy orthologs            
scoCount = len(sco_hits) 
for i in range(0, len(stats)):
    orthos = 0
    for index, row in orth_hits[scinames[i]].iteritems():
        if row != '*':
            add = row.count(',') + 1
            orthos += add
    singletons = 0
    for index, row in dftrim.iterrows():
        if row[scinames[i]] != '*':
            others = []
            for y in range(0, len(row)):
                others.append(row[y])
            others = set(others)
            if len(others) == 2:
                singletons += 1
    stats[i].append("{0:,}".format(singletons))
    stats[i].append("{0:,}".format(orthos))
    stats[i].append("{0:,}".format(scoCount))        
    summary.append(stats[i])

#convert to dataframe for easy output
header = ['species', 'isolate', 'Assembly Size', 'Largest Scaffold', 'Average Scaffold', 'Num Scaffolds', 'Scaffold N50', 'Percent GC', 'Num Genes', 'Num Proteins', 'Num tRNA', 'Unique Proteins', 'Prots atleast 1 ortholog', 'Single-copy orthologs']
df = pd.DataFrame(summary, columns=header)
df.set_index('species', inplace=True)
df.transpose().to_csv(os.path.join(args.out, 'stats','genome.stats.summary.csv'))
with open(os.path.join(args.out, 'stats.html'), 'w') as output:
    pd.set_option('display.max_colwidth', -1)
    output.write(lib.HEADER)
    output.write(lib.SUMMARY)
    output.write(df.transpose().to_html(classes='table table-condensed'))
    output.write(lib.FOOTER)
############################################

######summarize all annotation for each gene in a table
lib.log.info("Compiling all annotations for each genome")

#get orthology into dictionary
orthoDict = {}
if len(args.input) > 1:
    with open(orthologs, 'rU') as input:
        for line in input:
            line = line.replace('\n', '')
            col = line.split('\t')
            genes = col[1].split(',')
            for i in genes:
                orthoDict[i] = col[0]
            
#get GO associations into dictionary as well
with lib.suppress_stdout_stderr():
    goLookup = obo_parser.GODag(os.path.join(parentdir, 'DB', 'go.obo'))
goDict = {}
with open(os.path.join(go_folder, 'associations.txt'), 'rU') as input:
    for line in input:
        line = line.replace('\n', '')
        col = line.split('\t')
        gos = col[1].split(';')
        goList = []
        for i in gos:
            description = i+' '+goLookup[i].name
            goList.append(description)
        goDict[col[0]] = goList

EggNog = lib.eggnog2dict()
iprDict = lib.dictFlipLookup(ipr, INTERPRO)
pfamDict = lib.dictFlipLookup(pfam, PFAM)
meropsDict = lib.dictFlip(merops)  
cazyDict = lib.dictFlip(cazy)

table = []
header = ['GeneID','length','description', 'Ortho Group', 'EggNog', 'BUSCO','Protease family', 'CAZyme family', 'InterPro Domains', 'PFAM Domains', 'GO terms', 'SecMet Cluster', 'SMCOG']
for y in range(0,num_input):
    outputname = os.path.join(args.out, 'annotations', scinames[y]+'.all.annotations.tsv')
    with open(outputname, 'w') as output:
        output.write("%s\n" % ('\t'.join(header)))
        with open(gbkfilenames[y], 'rU') as input:
            SeqRecords = SeqIO.parse(input, 'genbank')
            for record in SeqRecords:
                for f in record.features:
                    if f.type == 'CDS':
                        egg = ''
                        cluster = ''
                        smcog = ''
                        ID = f.qualifiers['locus_tag'][0]
                        length = len(f.qualifiers['translation'][0])
                        description = f.qualifiers['product'][0]
                        if ID in iprDict:
                            IPRdomains = "; ".join(iprDict.get(ID))
                        else:
                            IPRdomains = ''
                        if ID in pfamDict:
                            pfamdomains = "; ".join(pfamDict.get(ID))
                        else:
                            pfamdomains = ''
                        if ID in meropsDict:
                            meropsdomains = "; ".join(meropsDict.get(ID))
                        else:
                            meropsdomains = ''
                        if ID in cazyDict:
                            cazydomains = "; ".join(cazyDict.get(ID))
                        else:
                            cazydomains = ''
                        if ID in busco[y]:
                            buscogroup = busco[y].get(ID)[0]
                        else:
                            buscogroup = ''
                        if ID in goDict:
                            goTerms = "; ".join(goDict.get(ID))
                        else:
                            goTerms = ''
                        if ID in orthoDict:
                            orthogroup = orthoDict.get(ID)
                        else:
                            orthogroup = ''
                        for k,v in f.qualifiers.items():
                            if k == 'note':
                                notes = v[0].split('; ')
                                for i in notes:
                                    if i.startswith('EggNog:'):
                                        hit = i.replace('EggNog:', '')
                                        egg = hit+': '+EggNog.get(hit)
                                    if i.startswith('antiSMASH:'):
                                        cluster = i.replace('antiSMASH:', '')
                                    if i.startswith('SMCOG:'):
                                        smcog = i

                        final_result = [ID, str(length), description, orthogroup, egg, buscogroup, meropsdomains, cazydomains, IPRdomains, pfamdomains, goTerms, cluster, smcog]
                        output.write("%s\n" % ('\t'.join(final_result)))        
############################################

#build phylogeny
if not os.path.isfile(os.path.join(args.out, 'phylogeny', 'RAxML.phylogeny.pdf')):
    if outgroup:
        num_phylogeny = len(args.input) + 1
    else:
        num_phylogeny = len(args.input)
    if num_phylogeny > 3:
        lib.log.info("Inferring phylogeny using RAxML")
        folder = os.path.join(args.out, 'protortho') 
        lib.ortho2phylogeny(folder, sco_final, args.num_orthos, busco, args.cpus, args.bootstrap, phylogeny, outgroup, outgroup_species, outgroup_name, sc_buscos)
    else:
        lib.log.info("Skipping RAxML phylogeny as at least 4 taxa are required")
    with open(os.path.join(args.out,'phylogeny.html'), 'w') as output:
        output.write(lib.HEADER)
        output.write(lib.PHYLOGENY)
        output.write(lib.FOOTER)

###########################################
def addlink(x):
    x = '<a href="http://eggnogdb.embl.de/#/app/results?target_nogs='+x+'">'+x+'</a>'
    return x
    
#building remaining HTML output
if len(args.input) > 1:
    with open(os.path.join(args.out, 'orthologs.html'), 'w') as output:  
        df = pd.read_csv(orthologs, sep='\t', header=None)
        orthtable = []
        for row in df.itertuples():
            t = row[2].split(', ') #convert Eggnog to list
            if t[0] == 'None':
                t = ['None']
            else:
                t = [ addlink(y) for y in t ]
            try:
                value = '; '.join(t)
            except TypeError:
                value = 'None found'
            final = [row[0], row[1], value, row[3], row[4]]
            orthtable.append(final)
        df2 = pd.DataFrame(orthtable)       
        df2.columns = ['Index', 'Orthology Group', 'EggNog Ref', 'BUSCOs','Gene Names']
        df2.set_index('Index', inplace=True)
        pd.set_option('display.max_colwidth', -1)
        output.write(lib.HEADER)
        output.write(lib.ORTHOLOGS)
        output.write(df2.to_html(index=False, escape=False, classes='table table-hover'))
        output.write(lib.FOOTER)
    
with open(os.path.join(args.out, 'citation.html'), 'w') as output:
    output.write(lib.HEADER)
    output.write(lib.CITATION)
    output.write(lib.FOOTER)
    
#make the "homepage"
date = datetime.now()
d = list(date.timetuple())

if d[3] > 12:
    hour = d[3] - 12
    m = 'pm'
else:
    hour = d[3]
    m = 'am'

d = [ str(x) for x in d ]

with open(os.path.join(args.out, 'index.html'), 'w') as output:
    output.write(lib.HEADER)
    output.write(lib.INDEX)
    output.write('<p>Report generated on: '+ d[1]+'/'+d[2]+'/'+d[0]+ ' at '+str(hour)+':'+d[4]+ ' '+m+'</p>')
    output.write(lib.FOOTER)
                       
lib.log.info("Compressing results to output file: %s.tar.gz" % args.out)
lib.make_tarfile(args.out+'.tar.gz', args.out)
lib.log.info("Finished!")
os._exit(1)


############################################



