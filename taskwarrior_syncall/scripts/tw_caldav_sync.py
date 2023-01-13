import os
from typing import List

import caldav
import click
from bubop import (
    check_optional_mutually_exclusive,
    format_dict,
    log_to_syslog,
    logger,
    loguru_tqdm_sink,
)

try:
    from taskwarrior_syncall import CaldavSide
except ImportError:
    inform_about_app_extras(["caldav-client"])

from taskwarrior_syncall import (
    Aggregator,
    TaskWarriorSide,
    __version__,
    cache_or_reuse_cached_combination,
    convert_caldav_to_tw,
    convert_tw_to_caldav,
    fetch_app_configuration,
    fetch_from_pass_manager,
    get_resolution_strategy,
    inform_about_app_extras,
    inform_about_combination_name_usage,
    list_named_combinations,
    opt_caldav_calendar,
    opt_caldav_passwd_pass_path,
    opt_caldav_url,
    opt_caldav_user_pass_path,
    opt_combination,
    opt_custom_combination_savename,
    opt_list_combinations,
    opt_resolution_strategy,
    opt_tw_project,
    opt_tw_tags,
    report_toplevel_exception,
)


@click.command()
# caldav options ---------------------------------------------------------------------
@opt_caldav_calendar()
@opt_caldav_url()
@opt_caldav_user_pass_path()
@opt_caldav_passwd_pass_path()
# taskwarrior options -------------------------------------------------------------------------
@opt_tw_tags()
@opt_tw_project()
# misc options --------------------------------------------------------------------------------
@opt_list_combinations("TW", "Caldav")
@opt_resolution_strategy()
@opt_combination("TW", "Caldav")
@opt_custom_combination_savename("TW", "Caldav")
@click.option("-v", "--verbose", count=True)
@click.version_option(__version__)
def main(
    caldav_calendar: str,
    caldav_url: str,
    caldav_user_pass_path: str,
    caldav_passwd_pass_path: str,
    tw_tags: List[str],
    tw_project: str,
    verbose: int,
    combination_name: str,
    custom_combination_savename: str,
    resolution_strategy: str,
    do_list_combinations: bool,
):
    """Synchronize calendars from your caldav Calendar with filters from Taskwarrior.

    The list of TW tasks is determined by a combination of TW tags and a TW project.
    The calendar in Caldav should be provided by their name. if it doesn't exist it will be created
    """

    loguru_tqdm_sink(verbosity=verbose)
    log_to_syslog(name="tw_caldav_sync")
    logger.debug("Initialising...")
    inform_about_config = False

    if do_list_combinations:
        list_named_combinations(config_fname="tw_caldav_configs")
        return 0

    check_optional_mutually_exclusive(combination_name, custom_combination_savename)
    combination_of_tw_project_tags_and_caldav_calendar = any(
        [
            tw_project,
            tw_tags,
            caldav_calendar,
        ]
    )
    check_optional_mutually_exclusive(
        combination_name, combination_of_tw_project_tags_and_caldav_calendar
    )

    # existing combination name is provided ---------------------------------------------------
    if combination_name is not None:
        app_config = fetch_app_configuration(
            config_fname="tw_caldav_configs", combination=combination_name
        )
        tw_tags = app_config["tw_tags"]
        tw_project = app_config["tw_project"]
        caldav_calendar = app_config["caldav_calendar"]

    # combination manually specified ----------------------------------------------------------
    else:
        inform_about_config = True
        combination_name = cache_or_reuse_cached_combination(
            config_args={
                "gcal_calendar": caldav_calendar,
                "tw_project": tw_project,
                "tw_tags": tw_tags,
            },
            config_fname="tw_caldav_configs",
            custom_combination_savename=custom_combination_savename,
        )

    # at least one of tw_tags, tw_project should be set ---------------------------------------
    if not tw_tags and not tw_project:
        raise RuntimeError(
            "You have to provide at least one valid tag or a valid project ID to use for"
            " the synchronization"
        )

    # announce configuration ------------------------------------------------------------------
    logger.info(
        format_dict(
            header="Configuration",
            items={
                "TW Tags": tw_tags,
                "TW Project": tw_project,
                "Caldav Calendar": caldav_calendar,
            },
            prefix="\n\n",
            suffix="\n",
        )
    )

    # initialize sides ------------------------------------------------------------------------
    tw_side = TaskWarriorSide(tags=tw_tags, project=tw_project)

    if not caldav_url or not caldav_calendar:
        logger.debug(caldav_url)
        logger.debug(caldav_calendar)
        raise RuntimeError(
            "You must provide a URL and calendar in order to synchronize via caldav"
        )

    # fetch username
    caldav_user = os.environ.get("CALDAV_USERNAME")
    if caldav_user is not None:
        logger.debug("Reading the caldav username from environment variable...")
    else:
        caldav_user = fetch_from_pass_manager(caldav_user_pass_path)
    assert caldav_user

    # fetch password
    caldav_passwd = os.environ.get("CALDAV_PASSWD")
    if caldav_passwd is not None:
        logger.debug("Reading the caldav password from environment variable...")
    else:
        caldav_passwd = fetch_from_pass_manager(caldav_passwd_pass_path)
    assert caldav_passwd

    client = caldav.DAVClient(url=caldav_url, username=caldav_user, password=caldav_passwd)
    caldav_side = CaldavSide(client=client, calendar_name=caldav_calendar)

    # sync ------------------------------------------------------------------------------------
    try:
        with Aggregator(
            side_A=caldav_side,
            side_B=tw_side,
            converter_B_to_A=convert_tw_to_caldav,
            converter_A_to_B=convert_caldav_to_tw,
            resolution_strategy=get_resolution_strategy(
                resolution_strategy, side_A_type=type(caldav_side), side_B_type=type(tw_side)
            ),
            config_fname=combination_name,
            ignore_keys=(
                (),
                ("due", "end", "entry", "modified", "urgency"),
            ),
        ) as aggregator:
            aggregator.sync()
    except KeyboardInterrupt:
        logger.error("Exiting...")
        return 1
    except:
        report_toplevel_exception(is_verbose=verbose >= 1)
        return 1

    if inform_about_config:
        inform_about_combination_name_usage(combination_name)

    return 0


if __name__ == "__main__":
    main()