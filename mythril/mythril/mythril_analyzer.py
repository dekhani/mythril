#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import traceback
from typing import Optional, List

from . import MythrilDisassembler
from mythril.support.source_support import Source
from mythril.support.loader import DynLoader
from mythril.analysis.symbolic import SymExecWrapper
from mythril.analysis.callgraph import generate_graph
from mythril.analysis.traceexplore import get_serializable_statespace
from mythril.analysis.security import fire_lasers, retrieve_callback_issues
from mythril.analysis.report import Report, Issue
from mythril.ethereum.evmcontract import EVMContract
from mythril.laser.smt import SolverStatistics
from mythril.support.start_time import StartTime

log = logging.getLogger(__name__)


class MythrilAnalyzer:
    """
    The Mythril Analyzer class
    Responsible for the analysis of the smart contracts
    """

    def __init__(
        self,
        disassembler: MythrilDisassembler,
        requires_dynld: bool = False,
        onchain_storage_access: bool = True,
        strategy: str = "dfs",
        address: Optional[str] = None,
        max_depth: Optional[int] = None,
        execution_timeout: Optional[int] = None,
        create_timeout: Optional[int] = None,
        enable_iprof: bool = False,
        transaction_sequences=None,
    ):
        """

        :param disassembler: The MythrilDisassembler class
        :param requires_dynld: whether dynamic loading should be done or not
        :param onchain_storage_access: Whether onchain access should be done or not
        """
        self.eth = disassembler.eth
        self.contracts = disassembler.contracts or []  # type: List[EVMContract]
        self.enable_online_lookup = disassembler.enable_online_lookup
        self.dynld = requires_dynld
        self.onchain_storage_access = onchain_storage_access
        self.strategy = strategy
        self.address = address
        self.max_depth = max_depth
        self.execution_timeout = execution_timeout
        self.create_timeout = create_timeout
        self.enable_iprof = enable_iprof
        self.transaction_sequences = transaction_sequences

    def dump_statespace(self, contract: EVMContract = None) -> str:
        """
        Returns serializable statespace of the contract
        :param contract: The Contract on which the analysis should be done
        :return: The serialized state space
        """
        sym = SymExecWrapper(
            contract or self.contracts[0],
            self.address,
            self.strategy,
            dynloader=DynLoader(
                self.eth,
                storage_loading=self.onchain_storage_access,
                contract_loading=self.dynld,
            ),
            max_depth=self.max_depth,
            execution_timeout=self.execution_timeout,
            create_timeout=self.create_timeout,
            enable_iprof=self.enable_iprof,
        )

        return get_serializable_statespace(sym)

    def graph_html(
        self,
        contract: EVMContract = None,
        enable_physics: bool = False,
        phrackify: bool = False,
        transaction_count: Optional[int] = None,
    ) -> str:
        """

        :param contract: The Contract on which the analysis should be done
        :param enable_physics: If true then enables the graph physics simulation
        :param phrackify: If true generates Phrack-style call graph
        :param transaction_count: The amount of transactions to be executed
        :return: The generated graph in html format
        """
        sym = SymExecWrapper(
            contract or self.contracts[0],
            self.address,
            self.strategy,
            dynloader=DynLoader(
                self.eth,
                storage_loading=self.onchain_storage_access,
                contract_loading=self.dynld,
            ),
            max_depth=self.max_depth,
            execution_timeout=self.execution_timeout,
            transaction_count=transaction_count,
            create_timeout=self.create_timeout,
            enable_iprof=self.enable_iprof,
        )
        return generate_graph(sym, physics=enable_physics, phrackify=phrackify)

    def fire_lasers(
        self,
        modules: Optional[List[str]] = None,
        verbose_report: bool = False,
        transaction_count: Optional[int] = None,
    ) -> Report:
        """
        :param modules: The analysis modules which should be executed
        :param verbose_report: Gives out the transaction sequence of the vulnerability
        :param transaction_count: The amount of transactions to be executed
        :return: The Report class which contains the all the issues/vulnerabilities
        """
        all_issues = []  # type: List[Issue]
        SolverStatistics().enabled = True
        exceptions = []
        for contract in self.contracts:
            StartTime()  # Reinitialize start time for new contracts
            try:
                sym = SymExecWrapper(
                    contract,
                    self.address,
                    self.strategy,
                    dynloader=DynLoader(
                        self.eth,
                        storage_loading=self.onchain_storage_access,
                        contract_loading=self.dynld,
                    ),
                    max_depth=self.max_depth,
                    execution_timeout=self.execution_timeout,
                    create_timeout=self.create_timeout,
                    transaction_count=transaction_count,
                    modules=modules,
                    compulsory_statespace=False,
                    enable_iprof=self.enable_iprof,
                    transaction_sequences=self.transaction_sequences,
                )
                issues = fire_lasers(sym, modules)
            except KeyboardInterrupt:
                log.critical("Keyboard Interrupt")
                issues = retrieve_callback_issues(modules)
            except Exception:
                log.critical(
                    "Exception occurred, aborting analysis. Please report this issue to the Mythril GitHub page.\n"
                    + traceback.format_exc()
                )
                issues = retrieve_callback_issues(modules)
                exceptions.append(traceback.format_exc())
            for issue in issues:
                issue.add_code_info(contract)

            all_issues += issues
            log.info("Solver statistics: \n{}".format(str(SolverStatistics())))

        source_data = Source()
        source_data.get_source_from_contracts_list(self.contracts)
        # Finally, output the results
        report = Report(verbose_report, source_data, exceptions=exceptions)
        for issue in all_issues:
            report.append_issue(issue)

        return report