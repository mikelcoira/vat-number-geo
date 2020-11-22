import argparse
import os
import re
import requests
from circuitbreaker import circuit
from pyVies import api


class HTTPError(Exception):
    """
    Base Exception thrown when there is an unexpected result
    retrieving an URL
    """
    pass


def normalize(vat_number):
    return vat_number.rstrip('\n').replace(' ', '').replace('*', '').upper()


class Validator(object):

    @staticmethod
    def validate(vat_number, vat_country_code):
        """
        Checks the format of the vat number according to the structure of VAT identification
        numbers that is defined in http://ec.europa.eu/taxation_customs/vies/faq.html#item_11

        Returns: True if the vat number matches with the format for the country specified in
        the argument vat_country_code or False otherwise.

        """
        vat_number_regexps = {
            'AT': re.compile(r'^ATU\d{8}$'),  # Austria
            'BE': re.compile(r'^BE0\d{9}$'),  # Belgium
            'BG': re.compile(r'^BG\d{9,10}$'),  # Bulgaria
            'CY': re.compile(r'^CY\d{8}\w$'),  # Cyprus
            'CZ': re.compile(r'^CZ\d{8,10}$'),  # Czech Republic
            'DE': re.compile(r'^DE\d{9}$'),  # Germany
            'DK': re.compile(r'^DK\d{2} \d{2} \d{2} \d{2}$'),  # Denmark
            'EE': re.compile(r'^EE\d{9}$'),  # Estonia
            'EL': re.compile(r'^EL\d{9}$'),  # Greece
            'ES': re.compile(r'^ES[\w\d]\d{7}[\w\d]$'),  # Spain
            'FI': re.compile(r'^FI\d{8}$'),  # Finland
            'FR': re.compile(r'^FR[\w\d]{2} \d{9}$'),  # France
            'GB': re.compile(
                r'^GB((\d{3} \d{4} \d{2})|(\d{3} \d{4} \d{2} \d{3})|((GD|HA)\d{3}))$'),  # United Kingdom
            'HR': re.compile(r'^HR\d{11}$'),  # Croatia
            'HU': re.compile(r'^HU\d{8}$'),  # Hungary
            'IE': re.compile(
                r'^IE((\d[\d\w\+\*]\d{5}\w)|(\d{7}WI))$'),  # Ireland
            'IT': re.compile(r'^IT\d{11}$'),  # Italy
            'LT': re.compile(r'^LT\d{9,12}$'),  # Lithuania
            'LU': re.compile(r'^LU\d{8}$'),  # Luxembourg
            'LV': re.compile(r'^LV\d{11}$'),  # Latvia
            'MT': re.compile(r'^MT\d{8}$'),  # Malta
            'NL': re.compile(r'^NL\d{9}B\d{2}$'),  # The Netherlands
            'PL': re.compile(r'^PL\d{10}$'),  # Poland
            'PT': re.compile(r'^PT\d{9}$'),  # Portugal
            'RO': re.compile(r'^RO\d{2,10}$'),  # Romania
            'SE': re.compile(r'^SE\d{12}$'),  # Sweden
            'SI': re.compile(r'^SI\d{8}$'),  # Slovenia
            'SK': re.compile(r'^SK\d{10}$'),  # Slovakia
        }

        return vat_number_regexps[vat_country_code].match(vat_number)


@circuit(failure_threshold=5, recovery_timeout=10, expected_exception=HTTPError)
def vies_validation(vat_number, country):
    """
    Checks if the company's vat number is registered in VIES (VAT Information Exchange System).

    VIES is a search engine (not a database) owned by the European Commission. The data is
    retrieved from national VAT databases when a search is made from the VIES tool. The search
    result that is displayed within the VIES tool can be in one of two ways; EU VAT information
    exists (valid) or it doesn't exist (invalid).

    The search is done using the VIES VAT web service.

    Args:
        vat_number: the vat number must include the country code according to the requirements
        of the VAT identification numbers format.
        country: the country code is a two letters code that represents the country as listed
        in the VAT identification numbers format requirements.

    Returns: True if the vat number exists in VIES or False if not.
    """
    vies = api.Vies()
    result_vies = vies.request(vat_number, country, extended_info=False)
    return result_vies.valid


def axesor_validation(vat_number):
    """
    For Spanish companies that are not registered in VIES, we must check if the vat number is valid.
    Axesor offers a web form to retrieve basic info about any Spanish company using its vat number.
    We take advantage of that service to check the companies' existence.

    When a company exists, the response redirects you to the company's detail page on Axesor's web
    using a 302 HTTP code. If the company doesn't exist, we receive a 200 code because it shows the
    form's default response webpage that shows 0 results for the query. Therefore, there is no need
    to parse the HTML code. We just use the HTTP code of the response.

    Args:
        vat_number: this service is just for Spanish companies, so the vat number if the CIF of the
        company.

    Returns: True if the vat number exists in Axesor's database or False if not.

    """
    url = f'https://www.axesor.es/buscar/empresas?q={vat_number}&tabActivo=empresas'
    response = requests.request(method="get", url=url, allow_redirects=False)

    if response.status_code == 200:
        return False
    elif response.status_code == 302:
        # with response.headers['Location'] we can access the destiny URL
        return True
    else:
        raise HTTPError("Unexpected result from axesor")


def locate_vax_number(source, output):
    error_msg = "Not Found"

    with open(source, 'r') as reader:
        with open(output, 'w') as writer:

            for line in reader.readlines():

                vat_number = normalize(line)

                print(f"Processing {vat_number}")

                if Validator.validate("ES" + vat_number, "ES"):

                    result = vies_validation("ES" + vat_number, "ES")

                    if result is True:
                        writer.write(f"{vat_number},ES,\n")
                    else:

                        if axesor_validation(vat_number) is True:
                            writer.write(f"{vat_number},ES,\n")
                        else:
                            writer.write(f"{vat_number},ES,{error_msg}\n")
                else:
                    # non-spanish vat numbers should have their country code and be in the vies system
                    if Validator.validate(vat_number, "GB") and vies_validation(vat_number, "GB"):
                        writer.write(f"{vat_number},GB,\n")
                    elif Validator.validate(vat_number, "DE") and vies_validation(vat_number, "DE"):
                        writer.write(f"{vat_number},DE,\n")
                    else:
                        writer.write(f"{vat_number},,{error_msg}\n")


def main():

    def dir_path(file):
        directory = os.path.dirname(file)
        if os.path.isdir(directory):
            return file
        else:
            raise argparse.ArgumentTypeError(f"{directory}/ is not a valid path")

    def file_path(file):
        if os.path.isfile(file):
            return file
        else:
            raise argparse.ArgumentTypeError(f"{file} is not a valid path")

    parser = argparse.ArgumentParser(description='Locate the countries of a list of vat numbers')
    parser.add_argument('-i', '--input', help='the input file', required=True, type=file_path)
    parser.add_argument('-o', '--output', help='the output file', required=True, type=dir_path)
    args = parser.parse_args()
    locate_vax_number(args.input, args.output)


if __name__ == "__main__":
    main()
