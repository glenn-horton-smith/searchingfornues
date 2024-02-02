This directory contains tools and information for exploring how
tree variables are defined and computed. It includes a one-off
source code scraper named "make_table.py", which can
* create a sqlite database of trees and their leaf variables including
  information on which source code files create  them, along with
  line numbers of where the variables are defined, filled, and
  commented upon;
* create a CSV file containing the same information;
* create an HTML table containing the same information in human
  readable form, with hyperlinks to the relevant lines in the source
  code.
