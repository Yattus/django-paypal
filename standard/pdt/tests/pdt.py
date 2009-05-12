"""
run this with ./manage.py test website
see http://www.djangoproject.com/documentation/testing/ for details
"""
from django.conf import settings
from django.core.urlresolvers import reverse
from django.shortcuts import render_to_response
from django.template import Context
from django.template.loader import get_template
from django.test import TestCase
from django.test.client import Client
from paypal.standard.pdt.forms import PayPalPDTForm
from paypal.standard.pdt.models import PayPalPDT
from paypal.standard.pdt.signals import pdt_successful, pdt_failed


class DummyPayPalPDT():
    
    def __init__(self, update_context_dict={}):
        self.context_dict = {'st': 'SUCCESS', 'custom':'cb736658-3aad-4694-956f-d0aeade80194',
                             'txn_id':'1ED550410S3402306', 'mc_gross': '225.00', 
                             'business': settings.PAYPAL_RECEIVER_EMAIL, 'error': 'Error code: 1234'}
        
        self.context_dict.update(update_context_dict)
        self.response = ''
        
    def update_with_get_params(self, get_params):
        if get_params.has_key('tx'):
            self.context_dict['txn_id'] = get_params.get('tx')
        if get_params.has_key('amt'):
            self.context_dict['mc_gross'] = get_params.get('amt')
        if get_params.has_key('cm'):
            self.context_dict['custom'] = get_params.get('cm')
            
    def _postback(self):
        """
        Perform a Fake PayPal PDT Postback request.
        """        
        t = get_template('pdt/fake_pdt_response.html')
        c = Context(self.context_dict)
        html = t.render(c)
        self.response = html
        return html

class PDTTest(TestCase):    
    def setUp(self):
        # set up some dummy PDT get parameters
        self.get_params = {"tx":"4WJ86550014687441", "st":"Completed", "amt":"225.00", "cc":"EUR",
                      "cm":"a3e192b8%2d8fea%2d4a86%2db2e8%2dd5bf502e36be", "item_number":"",
                      "sig":"blahblahblah"}
        
        # monkey patch the PayPalPDT._postback function
        self.dpppdt = DummyPayPalPDT()
        self.dpppdt.update_with_get_params(self.get_params)
        PayPalPDT._postback = self.dpppdt._postback
        
        # Every test needs a client.
        self.client = Client()

    def test_verify_postback(self):
        dpppdt = DummyPayPalPDT()
        paypal_response = dpppdt._postback()
        assert('SUCCESS' in paypal_response)
        self.assertEqual(len(PayPalPDT.objects.all()), 0)
        pdt_obj = PayPalPDT()
        pdt_obj.ipaddress = '127.0.0.1'
        pdt_obj.response = paypal_response
        pdt_obj._verify_postback()
        self.assertEqual(len(PayPalPDT.objects.all()), 0)
        self.assertEqual(pdt_obj.txn_id, '1ED550410S3402306')
        
    def test_pdt(self):        
        self.assertEqual(len(PayPalPDT.objects.all()), 0)        
        self.dpppdt.update_with_get_params(self.get_params)
        paypal_response = self.client.get(reverse('paypal-pdt'), self.get_params)
        self.assertContains(paypal_response, 'Transaction complete', status_code=200)
        self.assertEqual(len(PayPalPDT.objects.all()), 1)

    def test_pdt_signals(self):
        self.successful_pdt_fired = False        
        self.failed_pdt_fired = False
        
        def successful_pdt(sender, **kwargs):
            self.successful_pdt_fired = True
        pdt_successful.connect(successful_pdt)
            
        def failed_pdt(sender, **kwargs):
            self.failed_pdt_fired = True 
        pdt_failed.connect(failed_pdt)
        
        self.assertEqual(len(PayPalPDT.objects.all()), 0)        
        paypal_response = self.client.get(reverse('paypal-pdt'), self.get_params)
        self.assertContains(paypal_response, 'Transaction complete', status_code=200)        
        self.assertEqual(len(PayPalPDT.objects.all()), 1)
        self.assertTrue(self.successful_pdt_fired)
        self.assertFalse(self.failed_pdt_fired)        
        pdt_obj = PayPalPDT.objects.all()[0]
        self.assertEqual(pdt_obj.flag, False)
        
    def test_double_pdt_get(self):
        self.assertEqual(len(PayPalPDT.objects.all()), 0)            
        paypal_response = self.client.get(reverse('paypal-pdt'), self.get_params)
        self.assertContains(paypal_response, 'Transaction complete', status_code=200)
        self.assertEqual(len(PayPalPDT.objects.all()), 1)
        pdt_obj = PayPalPDT.objects.all()[0]        
        self.assertEqual(pdt_obj.flag, False)        
        paypal_response = self.client.get(reverse('paypal-pdt'), self.get_params)
        self.assertContains(paypal_response, 'Transaction complete', status_code=200)
        self.assertEqual(len(PayPalPDT.objects.all()), 1) # we don't create a new pdt        
        pdt_obj = PayPalPDT.objects.all()[0]
        self.assertEqual(pdt_obj.flag, False)

    def test_no_txn_id_in_pdt(self):
        self.dpppdt.context_dict.pop('txn_id')
        self.get_params={}
        paypal_response = self.client.get(reverse('paypal-pdt'), self.get_params)
        self.assertContains(paypal_response, 'Transaction Failed', status_code=200)
        self.assertEqual(len(PayPalPDT.objects.all()), 0)

    
    