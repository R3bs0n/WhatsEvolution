from django import forms


class PdfUploadForm(forms.Form):
    arquivo = forms.FileField(
        label="Arquivo PDF",
        widget=forms.ClearableFileInput(attrs={"accept": ".pdf", "class": "form-control"}),
    )
