create table if not exists srcfile (
    fileid integer primary key,
    filename text
);

create table if not exists tree (
    treeid integer primary key,
    treename text,
    treetitle text,
    tvarname text,
    fileid int,
    fileline int
);

create table if not exists branch (
    branchid integer primary key,
    treeid integer,
    branchname text,
    bleafdef text,
    bvalvarname text,
    fileid int,
    fileline int
);

create table if not exists srccomment (
    commentid integer primary key,
    commenttext text,
    branchid int,
    fileid int,
    fileline int
);

create table if not exists srcassign (
    assignid integer primary key,
    assigntext text,
    branchid int,
    fileid int,
    fileline int
);
