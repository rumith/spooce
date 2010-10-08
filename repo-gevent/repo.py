#!/usr/bin/python
# -*- coding: utf-8 -*-
from gevent import monkey; monkey.patch_socket()
from gevent.wsgi import WSGIServer
from ConfigParser import ConfigParser

from werkzeug import Request, Response
import logging, os, new, re, getopt, sys

from sqlalchemy.dialects import mysql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.types import String, Boolean, DateTime, Text, Integer
from sqlalchemy import Table, Column, MetaData, ForeignKey, Index, desc, create_engine
from simplejson import dumps as tojson, loads as fromjson

import hashlib, hmac, secret, gzip, cStringIO, StringIO, zlib

import secret, default

Session, Package = {}, {}

def __Package_init__(self, lang, appcode, versioncode, key, body):
    self.lang = lang
    self.appcode = appcode
    self.versioncode = versioncode
    mac = hmac.new(secret.PackageSecret, None, hashlib.md5)
    mac.update(key)
    self.key = mac.digest().encode('base64').strip()
    self.body = body


def __Package_repr__(self):
    return "<Package('%s', '%s')>"%(self.appcode, self.versioncode)


class Repo(object):
    def __init__(self):
        pass

    def __upload(self, req):
        if req.method == "GET":
            return [open('index.html').read()]
        elif req.method == "POST":
            try:
                session = Session()
                mac = hmac.new(secret.PackageSecret, None, hashlib.md5)
                mac.update(req.form["key"])
                regex = re.compile("^[0-9a-z\.\-_]+$")
                for a in ["appcode", "versioncode", "lang"]:
                    if not regex.match(req.form[a]):
                        session.close()
                        return ["Illegal required argument %s" % a]
                if session.query(Package).filter_by(lang=req.form["lang"], appcode=req.form["appcode"]).count() == 0:
                    session.add(Package(req.form["lang"], req.form["appcode"], req.form["versioncode"], req.form["key"], req.form["body"]))
                    session.commit()
                    session.close()
                    return ["Package uploaded"]
                elif session.query(Package).filter_by(lang=req.form["lang"], appcode=req.form["appcode"]).one().key != mac.digest().encode('base64').strip():
                    session.close()
                    return ["Unauthorized request"]
                else:
                    if session.query(Package).filter_by(lang=req.form["lang"], appcode=req.form["appcode"], versioncode=req.form["versioncode"]).count() == 0:
                        session.add(Package(req.form["lang"], req.form["appcode"], req.form["versioncode"], req.form["key"], req.form["body"]))
                    else:
                        session.query(Package).filter_by(lang=req.form["lang"], appcode=req.form["appcode"], versioncode=req.form["versioncode"]).one().body = req.form["body"]
                    print req.form["lang"], req.form["appcode"], req.form["versioncode"], req.form["key"]
                    session.commit()
                    session.close()
                    return ["Package uploaded"]
            except:
                logging.error("__upload failure", exc_info=1)
                session.close()
                return ["An unknown error has occured"]
        else:
            return ["Method not supported"]
    
    def __download(self, req):
        session = Session()
        try:
            lang, appcode, versioncode = req.path.split("/")[2:5]
            if session.query(Package).filter_by(lang=lang, appcode=appcode, versioncode=versioncode).count() == 1:
                res = session.query(Package).filter_by(lang=lang, appcode=appcode, versioncode=versioncode).one().body
                session.close()
                if "deflate" in req.accept_encodings:
                    res = StringIO.StringIO(zlib.compress(res)).getvalue()
                    encoding = "deflate"
                elif "gzip" in req.accept_encodings:
                    zbuf = cStringIO.StringIO()
                    zfile = gzip.GzipFile(mode = 'wb',  fileobj = zbuf, compresslevel = 5)
                    zfile.write(res)
                    zfile.close()
                    res = zbuf.getvalue()
                    encoding = "gzip"
                else:
                    encoding = "identity"
                return 200, encoding, [res]
        except:
            logging.error("__download failure", exc_info=1)
        session.close()
        return 404, "identity", [""]

    def __call__(self, env, start_response):
        req = Request(env)
        resp = Response(status=200, content_type="text/plain")
        if req.path == '/pkg/upload':
            resp.content_type="text/html"
            resp.response = self.__upload(req)
            return resp(env, start_response)
        elif req.path == '/pkg/sdk':
            resp.content_disposition="application/force-download"
            resp.content_type="application/python"
            resp.headers.add("Content-Disposition", "attachment; filename=appcfg.py")
            f = open("appcfg.py").read().replace("__REPO_UPLOAD__", '"%s"' % (req.host_url + 'pkg/upload'))
            resp.headers.add("Content-Length", str(len(f)))
            resp.response = [f]
            return resp(env, start_response)
        elif req.path.startswith('/pkg'):
            resp.status_code, resp.content_encoding, resp.response = self.__download(req)
            return resp(env, start_response)
        else:
            resp.status_code = 404
            resp.response = [""]
            return resp(env, start_response)



def main():
    configfile, port, log = default.config, default.port, default.log
    global Session, Package

    try:
        opts, args = getopt.getopt(sys.argv[1:], "c:", ["config="])
    except getopt.GetoptError, err:
        print str(err)
        sys.exit(1)

    for option, value in opts:
        if option in ("-c", "--config"):
            configfile = value

    Config = ConfigParser()
    Config.read(configfile)

    for section in ["Global", "MySQL"]:
        if not Config.has_section(section):
            print "Malformed configuration file"
            sys.exit()

    if Config.has_option('Global', 'port'):
        port = Config.get('Global', 'port')
    if Config.has_option('Global', 'log'):
        log = Config.get('Global', 'log')

    logging.basicConfig(filename=log, level=logging.DEBUG)

    params = {"host": "", "user": "", "database": "", "port": ""}
    for param in params:
        if not Config.has_option("MySQL", param):
            print "Malformed configuration file: mission option %s in section MySQL" % (param)
            sys.exit(1)
        params[param] = Config.get("MySQL", param)
 
    try:
        engine = create_engine("mysql+mysqldb://%s:%s@%s:%s/%s?charset=utf8&use_unicode=0" %
            (params["user"], secret.MySQL, params["host"], params["port"], params["database"]), pool_recycle=3600)
        Base = declarative_base(bind=engine)
        Session = sessionmaker(bind=engine)

        Package = new.classobj("package", (Base, ), {
            "__tablename__": 'package',
            "__table_args__": {'mysql_engine':'InnoDB', 'mysql_charset':'utf8'},
            "__init__": __Package_init__,
            "__repr__": __Package_repr__,
            "lang": Column(String(32), primary_key=True, autoincrement=False),
            "appcode": Column(String(32), primary_key=True, autoincrement=False),
            "versioncode": Column(String(32), primary_key=True, autoincrement=False),
            "key": Column(String(24)),
            "body": Column(Text(524288))
            })

        Base.metadata.create_all(engine)
    except:
        print "Failed to establish connection to the database"
        print "Check the log file for details"
        logging.error("DB connection failure", exc_info=1)
        sys.exit(1)

    server = WSGIServer(("0.0.0.0", int(port)), Repo())
    try:
        logging.info("Server running on port %s. Ctrl+C to quit" % port)
        server.serve_forever()
    except KeyboardInterrupt:
        server.stop()
        logging.info("Server stopped")


if __name__ == "__main__":
    main()
