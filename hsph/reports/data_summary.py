from corehq.apps.reports.standard import DatespanMixin, ProjectReportParametersMixin, CustomProjectReport
from corehq.apps.reports.datatables import DataTablesColumn, NumericColumn, DataTablesColumnGroup, DataTablesHeader
from corehq.apps.reports.generic import GenericTabularReport
from dimagi.utils.couch.database import get_db
from hsph.fields import IHForCHFField, SelectReferredInStatusField
from hsph.reports import HSPHSiteDataMixin
    
from collections import defaultdict
import numbers
from corehq.apps.reports import util

def numeric_cell(val):
    if isinstance(val, numbers.Number):
        return util.format_datatables_data(text=val, sort_key=val)
    else:
        return val

class DataSummaryReport(CustomProjectReport, ProjectReportParametersMixin,
                        DatespanMixin, HSPHSiteDataMixin):
    pass

class PrimaryOutcomeReport(GenericTabularReport, DataSummaryReport):
    """
    BetterBirth Shared Dropbox/Updated ICT package/Reporting Specs/Primary Outcome.xlsx
    """
    name = "Primary Outcome Report"
    slug = "hsph_primary_outcome"
    fields = ['corehq.apps.reports.fields.DatespanField',
              'hsph.fields.SelectReferredInStatusField',
              'hsph.fields.SiteField']

    show_all_rows_option = True

    @property
    def headers(self):

        maternal_deaths = NumericColumn("Maternal Deaths")
        maternal_near_miss = NumericColumn("Maternal Near Miss")
        still_births = NumericColumn("Still Births")
        neonatal_mortality = NumericColumn("Neonatal Mortality")

        outcomes_on_discharge = DataTablesColumnGroup("Outcomes on Discharge",
            maternal_deaths,
            still_births,
            neonatal_mortality)
        outcomes_on_discharge.css_span = 2

        outcomes_on_7days = DataTablesColumnGroup("Outcomes at 7 Days",
            maternal_deaths,
            maternal_near_miss,
            still_births,
            neonatal_mortality)
        outcomes_on_7days.css_span = 2

        positive_outcomes = DataTablesColumnGroup("Total Positive Outcomes",
            maternal_deaths,
            maternal_near_miss,
            still_births,
            neonatal_mortality)
        positive_outcomes.css_span = 2

        return DataTablesHeader(
            DataTablesColumn("Region"),
            DataTablesColumn("District"),
            DataTablesColumn("Site"),
            NumericColumn("Birth Events"),
            NumericColumn("Referred In Births"),
            outcomes_on_discharge,
            outcomes_on_7days,
            positive_outcomes,
            NumericColumn("Primary Outcome Yes"),
            NumericColumn("Primary Outcome No"),
            NumericColumn("Lost to Follow Up")
        )

    @property
    def rows(self):
        rows = []
        if not self.selected_site_map:
            self._selected_site_map = self.site_map
        
        site_keys = self.generate_keys()

        referred = self.request_params.get(SelectReferredInStatusField.slug)
        prefix = ['referred_in'] if referred else []
        startdate = self.datespan.startdate_param_utc[:10]
        enddate = self.datespan.enddate_param_utc[:10]

        fields = [
            'birthEvents',
            'referredInBirths',
            'maternalDeaths',
            'stillBirths',
            'neonatalMortality',
            'maternalDeaths7Days',
            'maternalNearMisses7Days',
            'stillBirths7Days',
            'neonatalMortalityEvents7Days',
            'totalMaternalDeaths',
            'totalMaternalNearMisses',
            'totalStillBirths',
            'totalNeonatalMortalityEvents',
            'positiveOutcome',
            'negativeOutcome',
            'lostToFollowUp'
        ]

        for key in site_keys:
            key[2] = str(key[2])  # wtf

            data = get_db().view('hsph/data_summary', 
                startkey=[self.domain] + prefix + ['region'] + key + [startdate], 
                endkey=[self.domain] + prefix + ['region'] + key + [enddate],
                reduce=True,
                wrapper=lambda r: r['value'])

            for item in data:
                row = list(self.get_site_table_values(key))
                row.extend(numeric_cell(item.get(f, 0)) for f in fields)

                rows.append(row)
        return rows


class SecondaryOutcomeReport(DataSummaryReport):
    """
    BetterBirth Shared Dropbox/Updated ICT package/Reporting Specs/Secondary
    Outcome.xlsx
    """
    name = "Secondary Outcome Report"
    slug = "hsph_secondary_outcome"
    fields = ['corehq.apps.reports.fields.DatespanField',
              'hsph.fields.SiteField']
    report_template_path = 'hsph/reports/comparative_data_summary.html'
    flush_layout = True

    @property
    def report_context(self):
        site_map = self.selected_site_map or self.site_map
        facilities = IHForCHFField.get_selected_facilities(
                site_map, domain=self.domain)

        return dict(
            ihf_data=self._get_data(facilities['ihf']),
            chf_data=self._get_data(facilities['chf'])
        )

    def _get_data(self, site_ids):
        startdate = self.datespan.startdate_param_utc[:10]
        enddate = self.datespan.enddate_param_utc[:10]

        def per(field, denom_field, denom_multiplier):
            def calculate(data):
                denom = data.get(denom_field, 0)
                if denom:
                    return denom_multiplier * data.get(field, 0) / float(denom)
                else:
                    return '---'
            return calculate

        extra_fields = {
            'maternalDeathsPer100000LiveBirths': per('totalMaternalDeaths', 'liveBirthsSum', 100000),
            'maternalNearMissesPer1000LiveBirths': per('totalMaternalNearMisses', 'liveBirthsSum', 1000),
            'referredInBirthsPer1000LiveBirths': per('referredInBirths', 'liveBirthsSum', 1000),
            'cSectionsPer1000LiveBirths': per('cSections', 'liveBirthsSum', 1000),
            'stillBirthsPer1000LiveBirths': per('totalStillBirthsSum', 'liveBirthsSum', 1000),
            'neonatalMortalityEventsPer1000LiveBirths': per('neonatalMortalityEvents7DaysSum', 'liveBirthsSum', 1000),
            'referredOutPer1000LiveBirths': per('referredOut', 'liveBirthsSum', 1000),
        }

        data = defaultdict(int)
        db = get_db()

        for site_id in site_ids:
            result = db.view('hsph/data_summary',
                reduce=True,
                startkey=[self.domain, "site", site_id, startdate],
                endkey=[self.domain, "site", site_id, enddate],
                wrapper=lambda r: r['value']
            ).first()

            if result:
                for field, value in result.items():
                    data[field] += value

        data.update(FADAObservationsReport.get_values(
                self.domain, (startdate, enddate), site_ids=site_ids))

        for k, calc in extra_fields.items():
            data[k] = calc(data)

        return data


class FADAObservationsReport(DataSummaryReport):
    """
    BetterBirth Shared Dropbox/Updated ICT package/Reporting Specs/FADA
    Observations - 2 _v6_ms.xls
    """
    name = "FADA Observations"
    slug = "fada_observations"

    fields = ['corehq.apps.reports.fields.DatespanField',
              'hsph.fields.NameOfFADAField',
              'hsph.fields.SiteField']

    report_template_path = 'hsph/reports/fada_observations.html'
    flush_layout = True

    @classmethod
    def get_values(cls, domain, daterange, site_ids=None, user_ids=None):
        """
        Gets reduced results per unique process_sbr_no for each key and sums
        them together, adding percentage occurences out of total_forms for all
        indicators.

        """

        site_ids = site_ids or []
        user_ids = user_ids or []
        startdate, enddate = daterange
        keys = []
        keys.extend([(["site", site_id, startdate],
                      ["site", site_id, enddate])
                     for site_id in site_ids])
        keys.extend([(["user", user_id, startdate],
                      ["user", user_id, enddate])
                     for user_id in user_ids])

        data_keys = [
            "total_forms",
            "pp1_observed",
            "pp1_maternal_temp",
            "pp1_maternal_bp",
            "pp1_partograph",
            "pp1_scc_used_pp1",
            "pp1_pp_1_birth_companion_present",
            "pp2_observed",
            "pp2_oxycotin_started",
            "pp2_soap",
            "pp2_water",
            "pp2_gloves_used",
            "pp2_scc_used_pp2",
            "pp2_pp3_birth_companion_present",
            "pp3_observed",
            "pp3_oxycotin",
            "pp3_baby_apneic",
            "pp3_baby_intervention",
            "pp3_pp_3_birth_companion_present",
            "pp4_observed",
            "pp4_baby_wt",
            "pp4_baby_temp",
            "pp4_breastfeeding",
            "pp4_scc_used_pp4",
            "pp4_pp_4_birth_companion_present",
            "medication_observed",
            "med_oxycotin_admin",
            "med_ab_mother",
            "med_mgsulp",
            "med_ab_baby",
            "med_art_mother",
            "med_art_baby",

            "pp2_soap_and_water"
        ]

        values = dict((k, 0) for k in data_keys)
        db = get_db()

        all_results = []

        for startkey, endkey in keys:
            results = db.view("hsph/fada_observations",
                reduce=True,
                group_level=5,
                startkey=[domain] + startkey,
                endkey=[domain] + endkey)

            all_results.extend(results)

        # "The same sbr no forms are definitely not going to come from
        # different users." -- Sheel
        seen_process_sbr_nos = set()
        for result in all_results:
            value = result['value']
            process_sbr_no = result['key'][4]

            if process_sbr_no not in seen_process_sbr_nos:
                if value['site_id'] in site_ids and value['user_id'] in user_ids:
                    for k, v in value.items():
                        if k not in ('site_id', 'user_id'):
                            values[k] += v
                seen_process_sbr_nos.add(process_sbr_no)

        for k, v in values.items():
            pp = ('medication' if k[:3] == 'med' else k[:3]) + "_observed"
            if pp in values:
                if values[pp]:
                    values[k + '_pct'] = round(float(v) * 100 / values[pp], 1)
                else:
                    values[k + '_pct'] = '---'

        # used by secondary outcome report
        if values['pp3_baby_apneic']:
            values['pp3_apneic_intervention_pct'] = round(
                100 * float(values['pp3_baby_intervention']) / values['pp3_baby_apneic'], 1)
        else:
            values['pp3_apneic_intervention_pct'] = '---'
        
        values['unique_sbrs'] = values['total_forms']

        return values

    @property
    def report_context(self):
        site_map = self.selected_site_map or self.site_map
        facilities = IHForCHFField.get_selected_facilities(site_map, self.domain)

        startdate = self.datespan.startdate_param_utc[:10]
        enddate = self.datespan.enddate_param_utc[:10]

        user_ids = self.user_ids

       
        return {
            'ihf': self.get_values(
                    self.domain, (startdate, enddate),
                    site_ids=facilities['ihf'],
                    user_ids=user_ids),
            'chf': self.get_values(
                    self.domain, (startdate, enddate),
                    site_ids=facilities['chf'],
                    user_ids=user_ids)
        }
