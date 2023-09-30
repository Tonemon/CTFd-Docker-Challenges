import tempfile
import traceback

from flask import Blueprint, render_template, request, jsonify
from sqlalchemy.exc import InternalError

from CTFd.api import CTFd_API_v1
from CTFd.models import Teams, Users, db
from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.challenges import CHALLENGE_CLASSES
from CTFd.utils.config import is_teams_mode
from CTFd.utils.decorators import admins_only

from .api import (active_docker_namespace, container_namespace,
                  docker_namespace, kill_container, secret_namespace)
from .functions.general import get_repositories, get_docker_info, do_request
from .models.container import DockerChallengeType
from .models.models import (DockerChallengeTracker, DockerConfig,
                            DockerConfigForm)
from .models.service import DockerServiceChallengeType


def handle_file_import(file_key: str, dockerconf: DockerConfig, attr_name: str):
    """ Imports the `request` POST `file_key` contents into the `DockerConfig` using `attr_name`. """
    if file_key not in request.files:
        setattr(dockerconf, attr_name, '')
        return

    try:
        file_content = request.files[file_key].stream.read()
        if len(file_content) != 0:
            setattr(dockerconf, attr_name, file_content)
            return
    except Exception as err:
        print(f"Error during file import: {err}")
        setattr(dockerconf, attr_name, '')



def define_docker_admin(app):
    admin_docker_config = Blueprint('admin_docker_config', __name__, template_folder='templates',
                                    static_folder='assets')

    @admin_docker_config.route("/admin/docker_config", methods=["GET", "POST"])
    @admins_only
    def docker_config():
        docker = DockerConfig.query.filter_by(id=1).first()
        form = DockerConfigForm()

        if docker:
            b = docker
        else:
            print('No docker config was found, setting empty one.')
            b = DockerConfig()
            db.session.add(b)
            db.session.commit()
            docker = DockerConfig.query.filter_by(id=1).first()

        if request.method == "POST":
            handle_file_import('ca_cert', b, 'ca_cert')
            handle_file_import('client_cert', b, 'client_cert')
            handle_file_import('client_key', b, 'client_key')

            b.hostname = request.form['hostname']

            b.tls_enabled = False
            if 'tls_enabled' in request.form:
                b.tls_enabled = request.form['tls_enabled'] == "True"

            if not b.tls_enabled:
                b.ca_cert = None
                b.client_cert = None
                b.client_key = None

            repositories = request.form.to_dict(flat=False).get('repositories', None)
            if repositories:
                b.repositories = ','.join(repositories)
            else:
                b.repositories = None

            db.session.add(b)
            db.session.commit()
            docker = DockerConfig.query.filter_by(id=1).first()

        try:
            repos = get_repositories(docker)
        except:
            print(traceback.print_exc())
            repos = list()

        if len(repos) == 0:
            form.repositories.choices = [("ERROR", "Failed to load repositories")]
        else:
            form.repositories.choices = [(d, d) for d in repos]

        dconfig = DockerConfig.query.first()
        try:
            selected_repos = dconfig.repositories
            if selected_repos == None:
                selected_repos = list()
        except:
            print(traceback.print_exc())
            selected_repos = []

        dinfo = get_docker_info(docker)

        return render_template("docker_config.html", config=dconfig, form=form, repos=selected_repos, info=dinfo)

    app.register_blueprint(admin_docker_config)


def define_docker_status(app):
    admin_docker_status = Blueprint('admin_docker_status', __name__, template_folder='templates',
                                    static_folder='assets')

    @admin_docker_status.route("/admin/docker_status", methods=["GET", "POST"])
    @admins_only
    def docker_admin():
        try:
            docker_tracker = DockerChallengeTracker.query.all()
            for i in docker_tracker:
                if is_teams_mode():
                    name = Teams.query.filter_by(id=i.team_id).first()
                    i.team_id = name.name
                else:
                    name = Users.query.filter_by(id=i.user_id).first()
                    i.user_id = name.name
        except InternalError as err:
            print(err)
            return render_template("admin_docker_status.html", dockers=[])

        return render_template("admin_docker_status.html", dockers=docker_tracker)

    app.register_blueprint(admin_docker_status)


def load(app):
    app.db.create_all()

    CHALLENGE_CLASSES['docker'] = DockerChallengeType
    CHALLENGE_CLASSES['docker_service'] = DockerServiceChallengeType

    register_plugin_assets_directory(app, base_path='/plugins/docker_challenges/assets')

    define_docker_admin(app)
    define_docker_status(app)

    CTFd_API_v1.add_namespace(docker_namespace, '/docker')
    CTFd_API_v1.add_namespace(container_namespace, '/container')
    CTFd_API_v1.add_namespace(active_docker_namespace, '/docker_status')
    CTFd_API_v1.add_namespace(kill_container, '/nuke')
    CTFd_API_v1.add_namespace(secret_namespace, '/secret')
