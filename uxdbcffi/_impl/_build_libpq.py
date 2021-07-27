""" CFFI interface to libpq the library """

from __future__ import print_function

from distutils import sysconfig
import os.path
import re
import sys
import subprocess

from cffi import FFI


PLATFORM_IS_WINDOWS = sys.platform.lower().startswith("win")
LIBRARY_NAME = "pq" if not PLATFORM_IS_WINDOWS else "libpq"


class PostgresConfig:
    def __init__(self):
        try:
            from uxdbcffi import _config
        except ImportError:
            self.pg_config_exe = None
            if not self.pg_config_exe:
                self.pg_config_exe = self.autodetect_pg_config_path()
            if self.pg_config_exe is None:
                # FIXME - do we need some way to set it?
                sys.stderr.write(
                    """\
Error: pg_config executable not found.
Please add the directory containing pg_config to the PATH.
"""
                )
                sys.exit(1)
            self.libpq_include_dir = self.query("includedir") or None
            self.libpq_lib_dir = self.query("libdir") or None
            self.libpq_version = self.find_version()
        else:
            self.libpq_include_dir = _config.PG_INCLUDE_DIR
            self.libpq_lib_dir = _config.PG_LIB_DIR
            self.libpq_version = _config.PG_VERSION

    def query(self, attr_name):
        """Spawn the pg_config executable, querying for the given config
        name, and return the printed value, sanitized."""
        try:
            pg_config_process = subprocess.Popen(
                [self.pg_config_exe, "--" + attr_name],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError:
            raise Warning(
                "Unable to find 'pg_config' file in '%s'" % self.pg_config_exe
            )
        pg_config_process.stdin.close()
        result = pg_config_process.stdout.readline().strip()
        if not result:
            raise Warning(pg_config_process.stderr.readline())
        if not isinstance(result, str):
            result = result.decode("ascii")
        return result

    def find_on_path(self, exename, path_directories=None):
        if not path_directories:
            path_directories = os.environ["PATH"].split(os.pathsep)
        for dir_name in path_directories:
            fullpath = os.path.join(dir_name, exename)
            if os.path.isfile(fullpath):
                return fullpath
        return None

    def autodetect_pg_config_path(self):
        """Find and return the path to the pg_config executable."""
        if PLATFORM_IS_WINDOWS:
            return self.autodetect_pg_config_path_windows()
        else:
            return self.find_on_path("pg_config")

    def autodetect_pg_config_path_windows(self):
        """Attempt several different ways of finding the pg_config
        executable on Windows, and return its full path, if found."""

        # This code only runs if they have not specified a pg_config option
        # in the config file or via the commandline.

        # First, check for pg_config.exe on the PATH, and use that if found.
        pg_config_exe = self.find_on_path("pg_config.exe")
        if pg_config_exe:
            return pg_config_exe

        # Now, try looking in the Windows Registry to find a PostgreSQL
        # installation, and infer the path from that.
        pg_config_exe = self._get_pg_config_from_registry()
        if pg_config_exe:
            return pg_config_exe

        return None

    def _get_pg_config_from_registry(self):
        try:
            import winreg
        except ImportError:
            import _winreg as winreg

        reg = winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE)
        try:
            pg_inst_list_key = winreg.OpenKey(
                reg, "SOFTWARE\\PostgreSQL\\Installations"
            )
        except EnvironmentError:
            # No PostgreSQL installation, as best as we can tell.
            return None

        try:
            # Determine the name of the first subkey, if any:
            try:
                first_sub_key_name = winreg.EnumKey(pg_inst_list_key, 0)
            except EnvironmentError:
                return None

            pg_first_inst_key = winreg.OpenKey(
                reg, "SOFTWARE\\PostgreSQL\\Installations\\" + first_sub_key_name
            )
            try:
                pg_inst_base_dir = winreg.QueryValueEx(
                    pg_first_inst_key, "Base Directory"
                )[0]
            finally:
                winreg.CloseKey(pg_first_inst_key)

        finally:
            winreg.CloseKey(pg_inst_list_key)

        pg_config_path = os.path.join(pg_inst_base_dir, "bin", "pg_config.exe")
        if not os.path.exists(pg_config_path):
            return None

        # Support unicode paths, if this version of Python provides the
        # necessary infrastructure:
        if sys.version_info[0] < 3 and hasattr(sys, "getfilesystemencoding"):
            pg_config_path = pg_config_path.encode(sys.getfilesystemencoding())

        return pg_config_path

    def find_version(self):
        try:
            # Here we take a conservative approach: we suppose that
            # *at least* PostgreSQL 7.4 is available (this is the only
            # 7.x series supported by psycopg 2)
            pgversion = self.query("version").split()[1]
        except:
            pgversion = "7.4.0"

        verre = re.compile(r"(\d+)\.(\d+)(?:(?:\.(\d+))|(devel|(alpha|beta|rc)\d+)?)")
        m = verre.match(pgversion)
        if m:
            pgmajor, pgminor, pgpatch = m.group(1, 2, 3)
            if pgpatch is None or not pgpatch.isdigit():
                pgpatch = 0
        else:
            sys.stderr.write(
                "Error: could not determine PostgreSQL version from '%s'" % pgversion
            )
            sys.exit(1)

        return int("%02X%02X%02X" % (int(pgmajor), int(pgminor), int(pgpatch)), 16)


_config = PostgresConfig()

ffi = FFI()

# order and comments taken from libpq (ctypes impl)

ffi.cdef(
    """

static int const _PG_VERSION;

// postgres_ext.h

typedef unsigned int Oid;

// See comment below.

static int const LIBPQ_DIAG_SEVERITY;
static int const LIBPQ_DIAG_SQLSTATE;
static int const LIBPQ_DIAG_MESSAGE_PRIMARY;
static int const LIBPQ_DIAG_MESSAGE_DETAIL;
static int const LIBPQ_DIAG_MESSAGE_HINT;
static int const LIBPQ_DIAG_STATEMENT_POSITION;
static int const LIBPQ_DIAG_INTERNAL_POSITION;
static int const LIBPQ_DIAG_INTERNAL_QUERY;
static int const LIBPQ_DIAG_CONTEXT;
static int const LIBPQ_DIAG_SOURCE_FILE;
static int const LIBPQ_DIAG_SCHEMA_NAME;
static int const LIBPQ_DIAG_TABLE_NAME;
static int const LIBPQ_DIAG_COLUMN_NAME;
static int const LIBPQ_DIAG_DATATYPE_NAME ;
static int const LIBPQ_DIAG_CONSTRAINT_NAME;
static int const LIBPQ_DIAG_SOURCE_LINE;
static int const LIBPQ_DIAG_SOURCE_FUNCTION;

// libpq-fe.h

typedef enum
{
 /*
  * Although it is okay to add to this list, values which become unused
  * should never be removed, nor should constants be redefined - that would
  * break compatibility with existing code.
  */
 CONNECTION_OK,
 CONNECTION_BAD,
 /* Non-blocking mode only below here */

 /*
  * The existence of these should never be relied upon - they should only
  * be used for user feedback or similar purposes.
  */
 CONNECTION_STARTED,   /* Waiting for connection to be made.  */
 CONNECTION_MADE,   /* Connection OK; waiting to send.    */
 CONNECTION_AWAITING_RESPONSE,  /* Waiting for a response from the
           * postmaster.    */
 CONNECTION_AUTH_OK,   /* Received authentication; waiting for
         * backend startup. */
 CONNECTION_SETENV,   /* Negotiating environment. */
 CONNECTION_SSL_STARTUP,  /* Negotiating SSL. */
 CONNECTION_NEEDED   /* Internal state: connect() needed */
} ConnStatusType;

typedef enum
{
 PGRES_POLLING_FAILED = 0,
 PGRES_POLLING_READING,  /* These two indicate that one may   */
 PGRES_POLLING_WRITING,  /* use select before polling again.   */
 PGRES_POLLING_OK,
 PGRES_POLLING_ACTIVE  /* unused; keep for awhile for backwards
         * compatibility */
} PostgresPollingStatusType;

typedef enum
{
 PGRES_EMPTY_QUERY = 0,  /* empty query string was executed */
 PGRES_COMMAND_OK,   /* a query command that doesn't return
         * anything was executed properly by the
         * backend */
 PGRES_TUPLES_OK,   /* a query command that returns tuples was
         * executed properly by the backend, PGresult
         * contains the result tuples */
 PGRES_COPY_OUT,    /* Copy Out data transfer in progress */
 PGRES_COPY_IN,    /* Copy In data transfer in progress */
 PGRES_BAD_RESPONSE,   /* an unexpected response was recv'd from the
         * backend */
 PGRES_NONFATAL_ERROR,  /* notice or warning message */
 PGRES_FATAL_ERROR,   /* query failed */
} ExecStatusType;

typedef enum
{
 PQTRANS_IDLE,    /* connection idle */
 PQTRANS_ACTIVE,    /* command in progress */
 PQTRANS_INTRANS,   /* idle, within transaction block */
 PQTRANS_INERROR,   /* idle, within failed transaction */
 PQTRANS_UNKNOWN    /* cannot determine status */
} PGTransactionStatusType;

typedef ... PGconn;
typedef ... PGresult;
typedef ... PGcancel;

typedef struct pgNotify
{
    char       *relname;  /* notification condition name */
    int        be_pid;    /* process ID of notifying server process */
    char       *extra;    /* notification parameter */
    ...;
} PGnotify;

// Database connection control functions

extern PGconn *PQconnectdb(const char *conninfo);
extern PGconn *PQconnectStart(const char *conninfo);
extern /*PostgresPollingStatusType*/ int PQconnectPoll(PGconn *conn);
extern void PQfinish(PGconn *conn);

// Connection status functions

extern /*ConnStatusType*/ int PQstatus(const PGconn *conn);
extern /*PGTransactionStatusType*/ int PQtransactionStatus(const PGconn *conn);
extern const char *PQparameterStatus(const PGconn *conn, const char *paramName);
extern int PQprotocolVersion(const PGconn *conn);
extern int PQserverVersion(const PGconn *conn);
extern char *PQerrorMessage(const PGconn *conn);
extern int PQsocket(const PGconn *conn);
extern int PQbackendPID(const PGconn *conn);

// Command execution functions

extern PGresult *PQexec(PGconn *conn, const char *query);
extern /*ExecStatusType*/ int PQresultStatus(const PGresult *res);
extern char *PQresultErrorMessage(const PGresult *res);
extern char *PQresultErrorField(const PGresult *res, int fieldcode);
extern void PQclear(PGresult *res);

// Retrieving query result information

extern int PQntuples(const PGresult *res);
extern int PQnfields(const PGresult *res);
extern char *PQfname(const PGresult *res, int field_num);
extern Oid PQftype(const PGresult *res, int field_num);
extern int PQfsize(const PGresult *res, int field_num);
extern int PQfmod(const PGresult *res, int field_num);
extern int PQgetisnull(const PGresult *res, int tup_num, int field_num);
extern int PQgetlength(const PGresult *res, int tup_num, int field_num);
extern char *PQgetvalue(const PGresult *res, int tup_num, int field_num);

// direct parsers - not part of libpq

int PQEgetlong(int64_t *val, const PGresult *res, int tup_num, int field_num);
int PQEgetint(int32_t *val, const PGresult *res, int tup_num, int field_num);
int PQEgetfloat(float *val, const PGresult *res, int tup_num, int field_num);
int PQEgetdouble(double *val, const PGresult *res, int tup_num, int field_num);

// Retrieving other result information

extern char *PQcmdStatus(PGresult *res);
extern char *PQcmdTuples(PGresult *res);
extern Oid PQoidValue(const PGresult *res); /* new and improved */

"""
)

if _config.libpq_version >= 0x090000:
    ffi.cdef(
        """
// Escaping string for inclusion in sql commands
extern char *PQescapeLiteral(PGconn *conn, const char *str, size_t len);
    """
    )

ffi.cdef(
    """
// Escaping string for inclusion in sql commands
extern size_t PQescapeStringConn(PGconn *conn,
    char *to, const char *from, size_t length,
    int *error);
extern size_t PQescapeString(char *to, const char *from, size_t length);
extern unsigned char *PQescapeByteaConn(PGconn *conn,
    const unsigned char *from, size_t from_length,
    size_t *to_length);
extern unsigned char *PQescapeBytea(const unsigned char *from, size_t from_length,
    size_t *to_length);
extern unsigned char *PQunescapeBytea(const unsigned char *strtext,
    size_t *retbuflen);

// Asynchronous Command Processing

extern int PQsendQuery(PGconn *conn, const char *query);
extern PGresult *PQgetResult(PGconn *conn);
extern int PQconsumeInput(PGconn *conn);
extern int PQisBusy(PGconn *conn);
extern int PQsetnonblocking(PGconn *conn, int arg);
extern int PQflush(PGconn *conn);

// Cancelling queries in progress

extern PGcancel *PQgetCancel(PGconn *conn);
extern void PQfreeCancel(PGcancel *cancel);
extern int PQcancel(PGcancel *cancel, char *errbuf, int errbufsize);
extern int PQrequestCancel(PGconn *conn);

// Functions Associated with the COPY Command

extern int PQgetCopyData(PGconn *conn, char **buffer, int async);
extern int PQputCopyEnd(PGconn *conn, const char *errormsg);
extern int PQputCopyData(PGconn *conn, const char *buffer, int nbytes);

// Miscellaneous functions

extern void PQfreemem(void *ptr);

// Notice processing

typedef void (*PQnoticeProcessor) (void *arg, const char *message);
extern PQnoticeProcessor PQsetNoticeProcessor(PGconn *conn,
    PQnoticeProcessor proc,
    void *arg);
extern PGnotify *PQnotifies(PGconn *conn);

// Large object
extern int lo_open(PGconn *conn, Oid lobjId, int mode);
extern Oid lo_create(PGconn *conn, Oid lobjId);
extern Oid lo_import(PGconn *conn, const char *filename);
extern int lo_read(PGconn *conn, int fd, char *buf, size_t len);
extern int lo_write(PGconn *conn, int fd, const char *buf, size_t len);
extern int lo_tell(PGconn *conn, int fd);
extern int lo_lseek(PGconn *conn, int fd, int offset, int whence);
extern int lo_close(PGconn *conn, int fd);
extern int lo_unlink(PGconn *conn, Oid lobjId);
extern int lo_export(PGconn *conn, Oid lobjId, const char *filename);
extern int lo_truncate(PGconn *conn, int fd, size_t len);

"""
)


C_SOURCE = """
#if (defined(_MSC_VER) && _MSC_VER < 1600)
    typedef __int32  int32_t;
    typedef __int64  int64_t;
#else
    #include <stdint.h>
#endif
#include <postgres_ext.h>
#include <libpq-fe.h>

int PQEgetlong(int64_t *raw_res, const PGresult *res, int tup_num, int field_num) {
    char *val = PQgetvalue(res, tup_num, field_num);
    if (!val) return -1;
    sscanf(val, "%ld", (long *)raw_res);
    return 0;
}

int PQEgetint(int32_t *raw_res, const PGresult *res, int tup_num, int field_num) {
    char *val = PQgetvalue(res, tup_num, field_num);
    if (!val) return -1;
    sscanf(val, "%d", (int *)raw_res);
    return 0;
}

int PQEgetfloat(float *raw_res, const PGresult *res, int tup_num, int field_num) {
    char *val = PQgetvalue(res, tup_num, field_num);
    if (!val) return -1;
    sscanf(val, "%f", raw_res);
    return 0;
}

int PQEgetdouble(double *raw_res, const PGresult *res, int tup_num, int field_num) {
    char *val = PQgetvalue(res, tup_num, field_num);
    if (!val) return -1;
    sscanf(val, "%lf", raw_res);
    return 0;
}

// Real names start with PG_DIAG_, but here we define our prefixes,
// because some are defined and some are not depending on pg version.

static int const LIBPQ_DIAG_SEVERITY = 'S';
static int const LIBPQ_DIAG_SQLSTATE = 'C';
static int const LIBPQ_DIAG_MESSAGE_PRIMARY = 'M';
static int const LIBPQ_DIAG_MESSAGE_DETAIL = 'D';
static int const LIBPQ_DIAG_MESSAGE_HINT = 'H';
static int const LIBPQ_DIAG_STATEMENT_POSITION = 'P';
static int const LIBPQ_DIAG_INTERNAL_POSITION = 'p';
static int const LIBPQ_DIAG_INTERNAL_QUERY = 'q';
static int const LIBPQ_DIAG_CONTEXT = 'W';
static int const LIBPQ_DIAG_SCHEMA_NAME = 's';
static int const LIBPQ_DIAG_TABLE_NAME = 't';
static int const LIBPQ_DIAG_COLUMN_NAME = 'c';
static int const LIBPQ_DIAG_DATATYPE_NAME  = 'd';
static int const LIBPQ_DIAG_CONSTRAINT_NAME = 'n';
static int const LIBPQ_DIAG_SOURCE_FILE = 'F';
static int const LIBPQ_DIAG_SOURCE_LINE = 'L';
static int const LIBPQ_DIAG_SOURCE_FUNCTION = 'R';
""" + """

static int const _PG_VERSION = {libpq_version};
""".format(
    libpq_version=_config.libpq_version
)


_or_empty = lambda x: [x] if x else []


C_SOURCE_KWARGS = dict(
    libraries=[LIBRARY_NAME],
    library_dirs=(
        _or_empty(sysconfig.get_config_var("LIBDIR")) + _or_empty(_config.libpq_lib_dir)
    ),
    include_dirs=(
        _or_empty(sysconfig.get_python_inc()) + _or_empty(_config.libpq_include_dir)
    ),
)


if hasattr(ffi, "set_source"):
    ffi.set_source("uxdbcffi._impl._libpq", C_SOURCE, **C_SOURCE_KWARGS)


if __name__ == "__main__":
    ffi.compile()
