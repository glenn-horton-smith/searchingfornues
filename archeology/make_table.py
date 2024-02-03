"""This is a monstrous one-off source code scraper written by Glenn 
Horton-Smith to try to extract human-readable definitions -- or at 
least some meaningful hints -- from a set of many source code files 
defining ROOT TTrees. 

Note python3.8 or greater is required because I like the := operator a lot.
"""

import csv
import html
import re
import shlex
import sqlite3
import sys


RE_TTREE_1 = re.compile(r'(\w+) *= *\w+ *-> *make *< *TTree *> *\( *"(\w+)" *')
RE_TTREE_2 = re.compile(r'(\w+) *= *new *TTree *\( *"(\w+)" *')
RE_TTREE_ARGS = re.compile(r', *"(.*)" *\)')

RE_BRANCH = re.compile(r'(\w+) *-> *Branch *\( *"(\w+)" *')
RE_BRANCH_ARGS_1 = re.compile(r', *&?([\w.]+) *, *"(\w+/?\w?)" *[,)]')
RE_BRANCH_ARGS_2 = re.compile(r', *([\w.]+) *, *"(\w+\[\w+\]/?\w?)" *[,)]')
RE_BRANCH_ARGS_3 = re.compile(r', *("[^"]+") *, *&?([\w.]+) *[,)]')
RE_BRANCH_ARGS_4 = re.compile(r", *&?([\w.]+) *[,)]")


def fill_db_tables(flist="TTree-making-files.txt", dbfn="treeinfo.db"):
    """Fills tables with information about ROOT TTrees inferred from
    the C++ source code that makes them.

    flist - name a file containing C++ source files to read, one per line.

    dbfn - name of a sqlite3 database file in which to store the information.
           The tables must have already been created in the database.
           See create_tables.sql for the SQL "create table" commands.

    Calls process_one_file() for each file in flist.
    """
    db = sqlite3.connect(dbfn, isolation_level=None)
    fin = open(flist)
    for fn in fin:
        process_one_file(fn.strip(), db)


def process_one_file(fn, db):
    """Fills tables with information about ROOT TTrees inferred from
    the C++ source code that makes them.

    fn - name of a C++ source file to process

    db - database connection object for sqlite3 database to update

    Basic idea:
        - Find calls to make<TTree> to obtain different names of trees created in various classes.
        - Find ->Branch calls and extract tree C++ variable name, branch names, C++ variable references, and "leaf" variable names.
        - Find comments on lines containing the C++ variable.
        - Find assignments to the variables.

    Tables in the SQL database file are filled with this info.
    See create_tables.sql for the table schema.

    Assumptions about input files:
     - All trees are made with statements that match
        (\w+) *= *(\w+) *-> *make *< *TTree *> *\( *"(\w+)" *
       or
        (\w+) *= *new *TTree *\( *"(\w+)" *
       followed immediately by
        , *"(.+)" *\)
       or something that will be saved and marked as uninterpretable.
       The first group of the first expression is the C++ variable name
       for the tree in the souce code, and the second group is the name
       of the tree in the ROOT file. The first group in the second
       expression is the tree title.
     - All branches are made with statements that match
        (\w+) *-> *Branch *\( *"(\w+)" *
       followed immediately by
        , *&?([\w.]+) *, *"(\w+/?\w?)" *[,)]
       or
        , *([\w.]+) *, *"(\w+\[\w+\]/?\w?)" *[,)]
       or
        , *("[^"]+") *, *&?([\w.]+) *[,)]
       or
        , *&?([\w.]+) *[,)]
       or something that will be saved and marked as uninterpretable.
       The first group of the first expression is the C++ variable name
       for the tree in the source code, and the second group is the name
       of the branch in the root file. The second expression finds the
       C++ variable for the branch data in the first argument in cases
       1, 2, and 4, but in the second argument in case 3. The other
       groups contain information about the "leaf" names and types:
       refer to the ROOT TTree documentation for details.
    """
    fin = open(fn)
    c = db.cursor()
    c.execute("SELECT fileid FROM srcfile WHERE filename=?;", (fn,))
    fids = c.fetchall()
    if len(fids) == 0:
        c.execute("INSERT INTO srcfile (filename) VALUES(?);", (fn,))
        db.commit()
        c.execute("SELECT fileid FROM srcfile WHERE filename=?;", (fn,))
        fids = c.fetchall()
    assert len(fids) == 1
    fileid = fids[0][0]
    # print(f"{fn} {fileid}")
    # - Find calls to make<TTree> to obtain different names of trees created in various classes.
    tid_by_tvarname = {}
    fileline = 0
    for line in fin:
        fileline += 1
        m = RE_TTREE_1.search(line)
        if not m:
            m = RE_TTREE_2.search(line)
        if not m:
            continue
        tvarname, treename = m.groups()
        m2 = RE_TTREE_ARGS.match(line[m.end() :])
        if m2:
            treetitle = m2.groups()[0]
        else:
            treetitle = line
        # print(tvarname, treename, treetitle)
        # check if (treename, fileid) already exists before inserting.
        c.execute(
            "SELECT treeid, treetitle, tvarname, fileline"
            " FROM tree WHERE treename = ? AND fileid = ?;",
            (treename, fileid),
        )
        tchecks = c.fetchall()
        if len(tchecks) == 0:
            # this should be the usual case for a new database
            c.execute(
                "INSERT INTO tree (treename, treetitle, tvarname, fileid, fileline) VALUES(?,?,?,?,?);",
                (treename, treetitle, tvarname, fileid, fileline),
            )
            db.commit()
            c.execute(
                "SELECT treeid, treetitle, tvarname, fileline"
                " FROM tree WHERE treename = ? AND fileid = ?;",
                (treename, fileid),
            )
            tchecks = c.fetchall()
        # print(tchecks)
        if len(tchecks) == 1:
            # possilble if rerunning scan over same file already processed
            # confirm tree info is consistent
            if tchecks[0][1:] != (treetitle, tvarname, fileline):
                raise RuntimeError(
                    f"Database inconsistency: found tree in {fn} "
                    f"{(treename, treetitle, tvarname, fileid, fileline)}"
                    " but found existing db entry "
                    f"{(treename, tchecks[0][1], tchecks[0][2], fileid, tchecks[0][3])}"
                )
        else:
            raise RuntimeError(
                f"Database error: {len(tchecks)} entries for "
                f"treename = {treename} in file {fn}"
            )
        tid = tchecks[0][0]
        tid_by_tvarname[tvarname] = tid
    # - Find ->Branch calls and extract tree C++ variable name, branch names, C++ variable references, and "leaf" variable names.
    branchid_by_bvalvarname = dict()
    fin.seek(0)
    fileline = 0
    for line in fin:
        fileline += 1
        m = RE_BRANCH.search(line)
        if m is None:
            continue
        tvarname, branchname = m.groups()
        s = line[m.end() :]
        if m2 := RE_BRANCH_ARGS_1.match(s):
            bvalvarname, bleafdef = m2.groups()
        elif m2 := RE_BRANCH_ARGS_2.match(s):
            bvalvarname, bleafdef = m2.groups()
        elif m2 := RE_BRANCH_ARGS_3.match(s):
            bleafdef, bvalvarname = m2.groups()
            bleafdef = branchname + " (" + bleafdef + ")"
        elif m2 := RE_BRANCH_ARGS_4.match(s):
            bvalvarname = m2.groups()[0]
            bleafdef = branchname + " (object)"
        else:
            raise RuntimeError(f"{fn}:{fileline}: Unrecognized Branch syntax {line}")
        # print(tvarname, branchname, bvalvarname, bleafdef)
        # Check for no tree id with this match, which can happen in
        # case of "rewrite" filter such as ./Selection/AnalysisTools/BDT_tool.cc,
        # which only reads a tree and adds branches to it, and does not create
        # a tree at any point.
        if tvarname not in tid_by_tvarname:
            # insert dummy value for this "ghost tree"
            treename = tvarname
            treetitle = ""
            c.execute(
                "INSERT INTO tree (treename, treetitle, tvarname, fileid, fileline) VALUES(?,?,?,?,?);",
                (tvarname, treetitle, tvarname, fileid, -1),
            )
            db.commit()
            c.execute(
                "SELECT treeid FROM tree WHERE treename = ? AND fileid = ?;",
                (treename, fileid),
            )
            tid = c.fetchall()[0][0]
            tid_by_tvarname[tvarname] = tid
        tid = tid_by_tvarname[tvarname]
        c.execute(
            "INSERT INTO branch (treeid,branchname,bleafdef,bvalvarname,fileid,fileline) VALUES(?,?,?,?,?,?);",
            (tid, branchname, bleafdef, bvalvarname, fileid, fileline),
        )
        c.execute(
            "SELECT branchid FROM branch WHERE treeid = ? AND branchname = ?;",
            (tid, branchname),
        )
        branchid_by_bvalvarname[bvalvarname] = c.fetchall()[0][0]
    # - Find comments and assigments on lines containing any "branch value" variable.
    fin.seek(0)
    fileline = 0
    for line in fin:
        fileline += 1
        line = line.strip()
        tokens = shlex.shlex(line)
        bvset = set(t for t in tokens if t in branchid_by_bvalvarname)
        for bv in bvset:
            branchid = branchid_by_bvalvarname[bv]
            if re.search(f"{bv}.*/[/*]", line) is not None:
                c.execute(
                    "INSERT INTO srccomment (commenttext,branchid,fileid,fileline) VALUES(?,?,?,?);",
                    (line, branchid, fileid, fileline),
                )
            # the assignment statement check below is pretty crude, would be nice to improve
            if re.search(f"{bv}[^=]*=[^=]", line) is not None:
                c.execute(
                    "INSERT INTO srcassign (assigntext,branchid,fileid,fileline) VALUES(?,?,?,?);",
                    (line, branchid, fileid, fileline),
                )
    db.commit()  # just in case
    c.close()


def write_csv_table(dbfn="treeinfo.db", csvout="treeinfo.csv"):
    """Writes a single csv file with comment and assignment statement
    information for each (leaf,tree,filename) combination, sorted
    by leaf name, tree name, and filename (in that order).

    dbfn: filename of sqlite3 database filled by fill_db_tables()

    csvout: output filename
    """
    assert csvout != dbfn
    db = sqlite3.connect(dbfn)
    wrt = csv.writer(open(csvout, "w"))
    wrt.writerow(
        [
            "leaf_def",
            "tree_name",
            "branch_creation_file_line",
            "source_file_comments",
            "source_file_assignments",
        ]
    )
    select1 = """SELECT bleafdef,treename,filename,branch.fileline,branchid,srcfile.fileid
FROM branch,tree,srcfile 
WHERE branch.fileid=srcfile.fileid and branch.treeid=tree.treeid
ORDER BY bleafdef,treename,filename;"""
    select_c = """SELECT fileline,commenttext
FROM srccomment
WHERE fileid=? and branchid=?;"""
    select_a = """SELECT fileline,assigntext
FROM srcassign
WHERE fileid=? and branchid=?;"""
    for row1 in db.execute(select1):
        bleafdef, treename, filename, fileline, branchid, fileid = row1
        comment_texts = "\n".join(
            f"{t[0]}: {t[1]}" for t in db.execute(select_c, (fileid, branchid))
        )
        assign_texts = "\n".join(
            f"{t[0]}: {t[1]}" for t in db.execute(select_a, (fileid, branchid))
        )
        wrt.writerow(
            [bleafdef, treename, f"{filename}:{fileline}", comment_texts, assign_texts]
        )


def html_td_row(row):
    """Formats one simple html row.
    Assumes items in input list are proper html."""
    return "<tr><td>" + "</td>\n<td>".join(row) + "</td></tr>\n"


def html_td_row_rowspan1(row, rowspan1):
    """Formats one html row with first column having given rowspan.
    Assumes items in input list are proper html."""
    return f"<tr><td rowspan={rowspan1}>" + "</td>\n<td>".join(row) + "</td></tr>\n"


def html_th_row(row):
    """Writes one simple html header row.
    Assumes items in input list are proper html."""
    return "<tr><th>" + "</th>\n<th>".join(row) + "</th></tr>\n"


def git_source_link(fname, fline, urlprefix):
    """Formats a link to the source code file and line for a repository
    browser such as github. Only the line number is shown and linked."""
    return f'<a href="{urlprefix}{fname}#L{fline}">' + html.escape(f":{fline}") + "</a>"


def write_html_table(
    dbfn="treeinfo.db",
    htmloutfn="treeinfo.html",
    git_sourcecode_prefix="https://github.com/ubneutrinos/searchingfornues/blob/v30genie/",
):
    """Writes html for a table containing comment and assignment
    statement information for each leaf definition and (tree name,
    source filename) combination, sorted by leaf definition first, then
    tree name and source filename (in that order). When the same leaf
    is in more than one tree or file, a rowspan is used to group all
    the definitions of the given leaf together.

    dbfn: filename of sqlite3 database filled by fill_db_tables()

    htmloutfn: output filename

    git_sourcecode_prefix: prefix to use for direct html links to source code,
    (e.g., https://github.com/ubneutrinos/searchingfornues/blob/v30genie/)"""
    assert htmloutfn != dbfn
    db = sqlite3.connect(dbfn)
    fout = open(htmloutfn, "w")
    select1 = """SELECT bleafdef,count(*) FROM branch GROUP BY bleafdef;"""
    select2 = """SELECT treename,filename,branch.fileline,branchid,srcfile.fileid
FROM branch,tree,srcfile 
WHERE branch.bleafdef=? AND branch.fileid=srcfile.fileid AND branch.treeid=tree.treeid
ORDER BY bleafdef,treename,filename;"""
    select_c = """SELECT fileline,commenttext
FROM srccomment
WHERE fileid=? and branchid=?;"""
    select_a = """SELECT fileline,assigntext
FROM srcassign
WHERE fileid=? and branchid=?;"""

    fout.write(
        """<style>
table, th, td {
  border-collapse: collapse;
  white-space: pre-line;
  border: 1px solid;
}
</style>
<table>
"""
    )
    fout.write(
        html_th_row(
            [
                "Leaf Def.",
                "Tree Name",
                "Branch Creation File Line",
                "Source File Comments",
                "Source File Assignments",
            ]
        )
    )

    for row1 in db.execute(select1):
        bleafdef, bcount = row1
        irow = 0
        for row2 in db.execute(select2, (bleafdef,)):
            irow += 1
            treename, filename, fileline, branchid, fileid = row2
            if filename.startswith("./"):
                filename = filename[2:]
            comment_texts = "<br/>\n".join(
                git_source_link(filename, cline, git_sourcecode_prefix)
                + html.escape(" " + ctext)
                for cline, ctext in db.execute(select_c, (fileid, branchid))
            )
            assign_texts = "<br/>\n".join(
                git_source_link(filename, aline, git_sourcecode_prefix)
                + html.escape(" " + atext)
                for aline, atext in db.execute(select_a, (fileid, branchid))
            )
            hrow = [
                bleafdef,
                treename,
                filename + git_source_link(filename, fileline, git_sourcecode_prefix),
                comment_texts,
                assign_texts,
            ]
            if irow == 1:
                if bcount > 1:
                    fout.write(html_td_row_rowspan1(hrow, bcount))
                else:
                    fout.write(html_td_row(hrow))
            else:
                fout.write(html_td_row(hrow[1:]))
        # end loop over (tree, file) for common bleafdef's
    # end loop over unique bleafdef's
    fout.write("</table>\n")
    fout.close()


def main(argv):
    """Usage:
        python3 make_table.py fill_db_tables [--help] [flist [dbfn]]
    or
        python3 make_table.py write_html_table [--help] [dbfn [csvout]]
    or
        python3 make_table.py write_csv_table [--help] [dbfn [htmlout]]

    Respective actions are taken using default file arguments.

    The destination sqlite3 file (default "treeinfo.db") must be created
    prior to running fill_db_tables. This can be done with the command
         sqlite3 treeinfo.db < create_tables.sql

    (Note this program requires python3.8 or greater.)
    """
    if len(argv) <= 1 or argv[1] == "--help":
        print(main.__doc__)
        return 1
    functions = {
        "fill_db_tables": fill_db_tables,
        "write_html_table": write_html_table,
        "write_csv_table": write_csv_table,
    }
    func_opt = argv[1]
    if func_opt not in functions:
        print("Error, unrecognized function ", func_opt)
        print("Use --help for usage.")
        return 1
    func = functions[func_opt]
    if "--help" in argv:
        print(func)
        print(func.__doc__)
        return 1
    try:
        func(*argv[2:])
        return 0
    except Exception as e:
        print("Function failed\n\n", e)
        print(*sys.exc_info()[2])
        print("\nUse --help for help.")
        return 2


if __name__ == "__main__":
    main(sys.argv)
